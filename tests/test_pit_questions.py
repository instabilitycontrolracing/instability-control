"""#453: questions during the 40 s pit-plan window go to the normal radio, orders still change the plan."""
import time, unittest
from engineer.pit import PitCrew


def crew():
    c = PitCrew.__new__(PitCrew)
    c.plan = {"tyres": False, "pressure": None, "fuel": 10.0, "fuel_why": "", "ws": False, "fr": False, "in_car": None}
    c.awaiting = time.time()
    c.said = []
    c.speak = lambda who, line: c.said.append(line)
    c.apply = lambda p: None
    c.send_clear = lambda: None
    c.tank = lambda: 100.0
    c.metric = lambda: True
    c._fuel_words = lambda p: "Fuel: 10 l."
    c.watch, c.dash = {}, {}
    return c


class PitQuestions(unittest.TestCase):
    def test_questions_fall_through(self):
        for q in ["how are the tyres", "how's it going", "what's the gap behind", "is it going to rain", "how are my tires looking"]:
            c = crew()
            self.assertFalse(c.answer(q), q)
            self.assertFalse(c.plan["tyres"], q)

    def test_orders_still_work(self):
        c = crew(); self.assertTrue(c.answer("four tyres please")); self.assertTrue(c.plan["tyres"])
        c = crew(); self.assertTrue(c.answer("can we do new tires")); self.assertTrue(c.plan["tyres"])
        c = crew(); self.assertTrue(c.answer("yes")); c = crew(); self.assertTrue(c.answer("go ahead"))
        c = crew(); self.assertTrue(c.answer("fill it up"))


if __name__ == "__main__":
    unittest.main()
