import os
import unittest
from datetime import datetime, timedelta
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from api.operations import load_report
from auth.repository import UserRepository
from knowledge.documents import KbDocumentRepository
from scripts.seed_operations import require_development, seed
from session.operations import ANSWER, AnswerRun, setup
from session.operations_maintenance import maintain
from session.operations_reports import SHANGHAI, ratio, windows
from session.operations_signals import keywords, normalize, similar
from session.repository import PostgresSessionRepository


class OperationsTests(unittest.TestCase):
    def test_shanghai_midnight_and_cross_month_windows(self):
        local = datetime.fromisoformat("2026-11-30T16:18:00+00:00")
        (start,end),(prior_start,prior_end) = windows(local,1)
        self.assertEqual(start.isoformat(), "2026-12-01T00:00:00+08:00")
        self.assertEqual(prior_start.isoformat(), "2026-11-30T00:00:00+08:00")
        self.assertEqual(prior_end.isoformat(), "2026-11-30T00:18:00+08:00")
        self.assertEqual((end-start),(prior_end-prior_start))
        self.assertEqual(windows(local,7)[0][0].day,25)
        self.assertEqual(windows(local,30)[0][0].day,2)

    def test_keywords_and_repeated_text(self):
        text = "选课：138 1234 5678、36010220050901512X、202601234567，alice@example.org"
        result = normalize(text)
        self.assertNotRegex(result,r"[0-9]")
        self.assertEqual(keywords(text), ["选课"])
        self.assertTrue(similar("什么时候能选课？","什么时候能选课"))
        self.assertFalse(similar("什么时候能选课","今天下雨吗"))
        self.assertIsNone(ratio(0,0))

    def test_answer_telemetry_distinguishes_miss_and_tool_failure(self):
        class Writer:
            def __init__(self): self.rows = []
            def submit(self, statement, values): self.rows.append((statement, values))
        writer = Writer()
        run = AnswerRun(writer, {"id":"uid","role":"user"})
        run.tool("knowledge_search", None, run.started, "选课", 0)
        run.tool("websearch", "timeout", run.started, "选课", None)
        run.event({"type":"done","final_answer":{"message_id":3,"sources":[]}})
        run.finish(error="interrupted")
        statement, answer = writer.rows[-1]
        self.assertEqual(statement, ANSWER)
        self.assertEqual(answer[6:10], ("knowledge_search",True,None,None))
        self.assertEqual(answer[11:16], (2,0,1,False,True))
        self.assertEqual(len(writer.rows), 3)

    def test_preview_refuses_non_development(self):
        uri = "postgresql://localhost/operations_dev"
        require_development(uri, {"APP_ENV":"development"})
        for env in ({}, {"APP_ENV":"production"}, {"APP_ENV":"development","NODE_ENV":"production"}):
            with self.assertRaises(SystemExit):
                require_development(uri, env)
        with self.assertRaises(SystemExit):
            require_development("postgresql://example.invalid/operations_dev", {"APP_ENV":"development"})


class OperationsDatabaseTests(unittest.TestCase):
    def test_reports_on_postgresql(self):
        dsn = os.getenv("LANGGRAPH_POSTGRES_URI")
        if not dsn:
            self.skipTest("LANGGRAPH_POSTGRES_URI is required for isolated PostgreSQL tests")
        schema = sql.Identifier("test_operations_" + uuid4().hex)
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
            try:
                conn.execute(sql.SQL("SET search_path TO {}").format(schema))
                UserRepository(conn).setup()
                PostgresSessionRepository(conn).setup()
                KbDocumentRepository(conn).setup()
                setup(conn)
                now = datetime.now(SHANGHAI)
                empty = load_report(conn,"overview",7,"all",now)
                self.assertTrue(all(day["active"] is None for day in empty["trend"][:-1]))
                seed(conn,now)
                with conn.transaction():
                    maintain(conn,now)
                def report(tab, role="all"):
                    return load_report(conn,tab,7,role,now)
                overview = report("overview")
                only_users = report("overview","user")
                self.assertLessEqual(only_users["cards"][0]["value"], overview["cards"][0]["value"])
                self.assertEqual(len(overview["trend"]),7)
                quality = report("quality")
                row = quality["metrics"]
                self.assertEqual(sum(x["count"] for x in quality["routes"]),row["answers"])
                self.assertEqual(sum(round(x["share"]*100) for x in quality["routes"]),10_000)
                self.assertEqual(row["missing"],ratio(row["missed"],row["retrieved"]))
                self.assertEqual(row["approval"],ratio(row["likes"],row["votes"]))
                self.assertEqual(row["feedback"],ratio(row["votes"],row["answers"]))
                self.assertGreater(quality["retention"][1]["eligible"],0)
                self.assertLessEqual(quality["retention"][7]["retained"],quality["retention"][7]["eligible"])
                knowledge = report("knowledge")
                self.assertTrue(knowledge["unused"])
                gap = knowledge["gaps"][0]["keyword"]
                conn.execute("INSERT INTO operations_gap_marks(keyword,state,marked_at) VALUES (%s,'fixed',%s)",
                             (gap,now-timedelta(seconds=5)))
                self.assertNotIn(gap,[entry["keyword"] for entry in report("knowledge")["gaps"]])
                conn.execute("""INSERT INTO operations_tools VALUES
                    ('new-gap',%s,'user','test','knowledge_search',NULL,17,%s,0)""",
                    (now-timedelta(seconds=3),gap))
                self.assertIn(gap,[entry["keyword"] for entry in report("knowledge")["gaps"]])
                system = report("system")
                self.assertTrue(all(r["total_p95"] >= r["total_p50"] for r in system["times"]))
                security = report("security")
                self.assertTrue(security["detections"]["crisis"]["data"])
                self.assertNotIn("user_id",repr(security))
                self.assertEqual(len(load_report(conn,"overview",1,"all",now)["trend"]),1)
                self.assertEqual(len(load_report(conn,"overview",30,"all",now)["trend"]),30)
                conn.execute("""
                    INSERT INTO operations_answers(id,occurred_at,role,user_id,route,success,first_ms,elapsed_ms,
                      searches,hits,empty_searches,cited,used_web,documents)
                    SELECT 'frequent-'||n,%s - ((n+1) * interval '1 second'),'user','anonymous-preview',
                      'direct',true,100,200,0,0,0,false,false,ARRAY[]::text[]
                    FROM generate_series(1,65) n
                """, (now,))
                with conn.transaction():
                    maintain(conn,now)
                alert = conn.execute("SELECT * FROM operations_alerts WHERE rule='frequency'").fetchone()
                self.assertEqual(alert["value"],1)
                self.assertIsNone(alert["recovered_at"])
                with conn.transaction():
                    maintain(conn,now+timedelta(hours=2))
                resolved = conn.execute("SELECT recovered_at FROM operations_alerts WHERE id=%s", (alert["id"],)).fetchone()
                self.assertIsNotNone(resolved["recovered_at"])
            finally:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))
