"""The accuracy-evaluation script: interval maths and an end-to-end run on synthetic data."""

import base64
import importlib.util
import tempfile
import unittest
from pathlib import Path

from fras.biometrics.providers import DevProvider
from fras.biometrics.synthetic import frames_for

spec = importlib.util.spec_from_file_location("evalbio", Path(__file__).resolve().parents[1] / "scripts" / "evaluate_biometrics.py")
evalbio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evalbio)


class EvalScriptTests(unittest.TestCase):
    def test_wilson_interval_is_honest_at_zero_errors(self):
        lo, hi = evalbio.wilson(0, 100)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.03)          # 0 errors in 100 trials does not prove FAR < 3%
        self.assertEqual(evalbio.wilson(0, 0), (0.0, 1.0))

    def test_end_to_end_on_synthetic_people(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind, people in (("enrolled", range(5)), ("visitors", range(50, 52))):
                for p in people:
                    d = Path(tmp, kind, f"p{p}")
                    d.mkdir(parents=True)
                    for i, f in enumerate(frames_for(p, 5)):
                        (d / f"{i}.jpg").write_bytes(base64.b64decode(f.split(",", 1)[1]))
            r = evalbio.evaluate(DevProvider(), Path(tmp, "enrolled"), Path(tmp, "visitors"), 3)
            s = evalbio.summarize(r)
        self.assertEqual((r["people_enrolled"], r["probes"], r["open_set_probes"]), (5, 10, 10))
        self.assertEqual(len(r["impostor_closed"]), 10)
        self.assertTrue(any("impostor comparisons" in w for w in s["warnings"]))   # tiny sample is flagged
        md = evalbio.markdown(r, s, "dev")
        self.assertIn("not face recognition", md)
