"""Run from repo root: python3 -m unittest discover -s tools/jobintel/tests -t ."""
import json
import os
import unittest
from datetime import datetime, timezone, timedelta

from tools.jobintel import ingest, refresh, verify, get_adapter, score, resolve, check
from tools.jobintel.adapters import seek

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "seek_sample.json")
NOW = datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc)


def recs():
    with open(FIX, encoding="utf-8") as f:
        return json.load(f)


class Parse(unittest.TestCase):
    def test_nested_and_html(self):
        j = seek.parse(recs()[0])
        self.assertEqual(j["xid"], "seek:80000001")
        self.assertEqual(j["u"], "https://www.seek.com.au/job/80000001")
        self.assertTrue(j["u_orig"].endswith("ref=search-standalone"))
        self.assertIn("Build and deploy", j["desc"])
        self.assertEqual(j["cls"]["sub"], "Engineering - Software")
        self.assertEqual(j["wa"], ["Hybrid"])
        self.assertTrue(j["flags"]["is_expired"])

    def test_salary(self):
        j = seek.parse(recs()[1])
        self.assertEqual((j["sal"]["ann_min"], j["sal"]["ann_max"], j["sal"]["per"]), (140000, 155000, "year"))
        self.assertEqual(seek.parse_salary("$55 - $65 per hour")["ann_min"], 55 * 38 * 52)
        self.assertEqual(seek.parse_salary("$140k - $160k + super")["ann_max"], 160000)

    def test_camelcase(self):
        j = seek.parse(recs()[2])
        self.assertEqual(j["xid"], "seek:80000002")
        self.assertEqual(j["u"], "https://www.seek.com.au/job/80000002")
        self.assertEqual(j["wt"], "Full time")

    def test_nulls_do_not_crash(self):
        j = seek.parse(recs()[3])
        self.assertEqual(j["u"], "https://www.seek.com.au/job/80000003")
        self.assertIsNone(j["sal"]); self.assertEqual(j["desc"], "")
        for junk in ({}, {"id": None}, {"salary": {"min": "abc"}}, {"location": [None]}, [], None, "x"):
            seek.parse(junk)


class Status(unittest.TestCase):
    def st(self, i, **kw):
        j = seek.parse(recs()[i]); p = check(j, "seek", {"method": "user_supplied"}, NOW)
        return resolve(j, p, kw.get("v"), NOW)["st"]

    def test_expired_never_active(self):
        self.assertEqual(self.st(0), "expired")
        self.assertEqual(self.st(0, v={"state": "live", "at": NOW.isoformat(), "via": "user_check"}), "expired")

    def test_active_and_unknown(self):
        self.assertEqual(self.st(1), "active")
        self.assertEqual(self.st(3), "unknown")

    def test_verification(self):
        self.assertEqual(self.st(1, v={"state": "closed", "via": "user_check"}), "closed")
        self.assertEqual(self.st(1, v={"state": "gone", "via": "user_check"}), "unavailable")

    def test_low_trust_not_active(self):
        j = seek.parse(recs()[1]); p = check(j, "seek", {"method": "unknown"}, NOW)
        self.assertEqual(p["trust"], "low")
        self.assertEqual(resolve(j, p, None, NOW)["st"], "unknown")


class Provenance(unittest.TestCase):
    def test_lookalike_host_rejected(self):
        p = check(seek.parse(recs()[4]), "seek", {"method": "user_supplied"}, NOW)
        self.assertEqual(p["trust"], "reject")

    def test_scrape_blocked(self):
        p = check(seek.parse(recs()[1]), "seek", {"method": "third_party_scrape"}, NOW)
        self.assertEqual(p["trust"], "reject")


class Match(unittest.TestCase):
    def test_good_fit(self):
        m = score(seek.parse(recs()[1]))
        self.assertGreaterEqual(m["overall"], 75, m); self.assertEqual(m["band"], "high"); self.assertFalse(m["x"])

    def test_hard_exclusions(self):
        for i in (0, 5):
            m = score(seek.parse(recs()[i]))
            self.assertEqual((m["overall"], m["band"]), (0, "excluded"), m["x"])


class StoreFlow(unittest.TestCase):
    def test_ingest_dedup_history(self):
        jobs = [{"co": "sampleoilseeds", "t": "Senior Mechanical Project Engineer", "loc": "Smithfield, Sydney NSW",
                 "u": "https://www.seek.com.au/job/80000002", "src": "Seek", "d": "2026-11-20"}]
        jobs, rep = ingest(recs(), jobs, "seek", {"method": "user_supplied"}, now=NOW)
        self.assertEqual(len(rep["quarantined"]), 1)
        self.assertEqual(sum(1 for j in jobs if j.get("u") == "https://www.seek.com.au/job/80000002"), 1)
        j2 = next(j for j in jobs if j.get("xid") == "seek:80000002")
        self.assertIn("sal", j2["hist"][-1]["ch"])  # second copy raised the max salary
        self.assertEqual(len(jobs), 4)  # 6 in: 1 quarantined, 2 merged into the legacy record
        exp = next(j for j in jobs if j.get("xid") == "seek:80000001")
        self.assertEqual(exp["st"], "expired")
        # time passes: active job expires and is kept as history
        ch = refresh(jobs, NOW + timedelta(days=30))
        self.assertIn(("seek:80000002", "active", "expired"), ch)
        self.assertEqual(len(jobs), 4)
        verify(jobs, "seek:80000002", "live", "user_check", now=NOW + timedelta(days=30))
        self.assertEqual(j2["st"], "expired")

    def test_cross_source_dedup(self):
        jobs, _ = ingest(recs()[1], [], "seek", {"method": "user_supplied"}, now=NOW)
        lj = {"@type": "JobPosting", "title": "Senior Mechanical Project Engineer", "identifier": "R-77",
              "url": "https://careers.sampleoilseeds.example/jobs/R-77",
              "hiringOrganization": {"name": "Sample Oilseeds"},
              "jobLocation": {"address": {"addressLocality": "Sydney", "addressRegion": "NSW"}},
              "datePosted": "2026-11-21", "validThrough": "2026-12-21",
              "description": "<p>Lead brownfield capital projects at our edible oil refinery with pumps and piping to AS 4041.</p>"}
        jobs, rep = ingest(lj, jobs, None, {"method": "careers_page_jsonld"}, now=NOW)
        self.assertEqual(len(jobs), 1)
        self.assertIn("careers.sampleoilseeds.example:R-77", jobs[0].get("alt", []))

    def test_relist_kept_separate(self):
        a = dict(recs()[1]); b = dict(recs()[1], id="80000099", url="https://www.seek.com.au/job/80000099")
        jobs, _ = ingest([a, b], [], "seek", {"method": "user_supplied"}, now=NOW)
        self.assertEqual(len(jobs), 2); self.assertEqual(jobs[1]["dup"], "seek:80000002")


if __name__ == "__main__":
    unittest.main()
