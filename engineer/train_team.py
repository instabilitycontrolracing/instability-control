"""Fine-tune the team model (LoRA) on the examples from dataset.py, then merge.
Run with the game closed (uses the RTX 3080 Ti):  python -m engineer.train_team team_train.jsonl
"""
import json, os, sys, math, random, time
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, get_cosine_schedule_with_warmup
from peft import LoraConfig, get_peft_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "llm", "base", "Qwen3-4B-Instruct-2507")
OUT = os.path.join(ROOT, "llm", "race-team-lora")
MERGED = os.path.join(ROOT, "llm", "race-team-merged")
MAXLEN = 2560


def load(path):
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    random.Random(1).shuffle(rows)
    return rows


def encode(tok, ex):
    msgs = ex["messages"]
    prompt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
    full = prompt + msgs[-1]["content"] + tok.eos_token
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    f_ids = tok(full, add_special_tokens=False)["input_ids"][:MAXLEN]
    labels = [-100] * min(len(p_ids), len(f_ids)) + f_ids[len(p_ids):]
    return f_ids, labels[:len(f_ids)]


def main(data_path, epochs=2, lr=1.5e-4):
    dev = "cuda:0"
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.bfloat16, device_map={"": dev},
                                                 attn_implementation="sdpa")
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    cfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, cfg)
    model.print_trainable_parameters()
    rows = load(data_path)
    n_val = max(20, len(rows) // 25)
    val, train = rows[:n_val], rows[n_val:]
    enc = [encode(tok, r) for r in train]
    enc = [e for e in enc if any(x != -100 for x in e[1])]
    accum = 8
    steps = math.ceil(len(enc) / accum) * epochs
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr, weight_decay=0.0)
    sch = get_cosine_schedule_with_warmup(opt, int(steps * 0.05), steps)
    model.train()
    step, t0 = 0, time.time()
    log = open(os.path.join(ROOT, "llm", "train_log.txt"), "w")
    for ep in range(epochs):
        random.Random(ep).shuffle(enc)
        running = 0.0
        for i, (ids, lab) in enumerate(enc):
            x = torch.tensor([ids], device=dev); y = torch.tensor([lab], device=dev)
            loss = model(input_ids=x, labels=y).loss / accum
            loss.backward()
            running += loss.item()
            if (i + 1) % accum == 0 or i == len(enc) - 1:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step(); sch.step(); opt.zero_grad(set_to_none=True)
                step += 1
                if step % 10 == 0:
                    msg = f"epoch {ep + 1} step {step}/{steps} loss {running / 10:.4f} lr {sch.get_last_lr()[0]:.2e} {time.time() - t0:.0f}s"
                    print(msg, flush=True); log.write(msg + "\n"); log.flush()
                    running = 0.0
        # quick validation loss
        model.eval()
        with torch.no_grad():
            vl = []
            for r in val[:40]:
                ids, lab = encode(tok, r)
                vl.append(model(input_ids=torch.tensor([ids], device=dev), labels=torch.tensor([lab], device=dev)).loss.item())
        msg = f"epoch {ep + 1} validation loss {sum(vl) / len(vl):.4f}"
        print(msg, flush=True); log.write(msg + "\n"); log.flush()
        model.train()
    model.save_pretrained(OUT)
    print("merging...", flush=True)
    model = model.merge_and_unload()
    model.save_pretrained(MERGED, safe_serialization=True)
    tok.save_pretrained(MERGED)
    log.write("DONE\n"); log.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "llm", "team_train.jsonl"))
