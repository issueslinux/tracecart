"""Durable, coalesced graph questions for CartResearchJobs; no cart mutation."""
from datetime import datetime,timezone
import json


class GraphQuestionReviewMixin:
    def graph_question_review(self,job_id,current_digest=None):
        with self._db() as db:
            row=db.execute("""SELECT evidence_digest,status,questions_json,
                runs,error_type FROM cart_graph_question_review
                WHERE job_id=?""",(job_id,)).fetchone()
        if not row:
            return {"status":"NOT_SCHEDULED","questions":[],"runs":0}
        digest,status,raw,runs,error=row
        if current_digest is not None and digest!=current_digest:
            status="STALE_AFTER_GRAPH_CHANGE"
            raw="[]"
        return {"status":status,"questions":json.loads(raw),
                "runs":runs,"error_type":error}

    def schedule_graph_question_review(self,job_id):
        """One outstanding task per cart, four outstanding carts globally."""
        if self.model_stop.is_set():return False
        from cart_research import research_cart
        if self.runner is not research_cart:return False
        with self._graph_question_lock:
            if job_id in self._graph_question_pending or len(
                    self._graph_question_pending)>=4:
                return False
            self._graph_question_pending.add(job_id)
        try:
            self.model_pool.submit(self._graph_question_worker,job_id)
        except RuntimeError:
            with self._graph_question_lock:
                self._graph_question_pending.discard(job_id)
            return False
        return True

    def _graph_question_worker(self,job_id):
        """At most 2 calls/job; a changed graph invalidates in-flight output."""
        from graph_question_review import MAX_RUNS,graph_context,eligible,ask_local_llm
        from guided_decision import build_decision_projection
        from offer_knowledge_graph import build_offer_knowledge_graph
        retry=False
        try:
            record=self.read(job_id)
            if record["state"] not in ("READY","RUNNING"):return
            proj=build_decision_projection(record)
            context,digest=graph_context(proj,build_offer_knowledge_graph(proj))
            if not eligible(context):return
            with self._db() as db:
                previous=db.execute("""SELECT evidence_digest,status,runs
                    FROM cart_graph_question_review WHERE job_id=?""",
                    (job_id,)).fetchone()
                if previous and (
                    previous[2]>=MAX_RUNS or
                    (previous[0]==digest and previous[1] in
                     ("COMPLETE","NO_NEW_QUESTIONS","UNAVAILABLE","RUNNING"))):
                    return
                runs=(previous[2] if previous else 0)+1
                db.execute("""INSERT INTO cart_graph_question_review
                    (job_id,evidence_digest,status,questions_json,runs,updated_at)
                    VALUES (?,?,'RUNNING','[]',?,?)
                    ON CONFLICT(job_id) DO UPDATE SET
                    evidence_digest=excluded.evidence_digest,
                    status='RUNNING',questions_json='[]',
                    runs=excluded.runs,updated_at=excluded.updated_at,
                    error_type=NULL""",
                    (job_id,digest,runs,datetime.now(timezone.utc).isoformat()))
            self.live_bus.signal(job_id)
            status="NO_NEW_QUESTIONS";questions=[];error=None
            try:
                questions=ask_local_llm(context)
                if questions:status="COMPLETE"
            except (OSError,ValueError,TypeError,KeyError,TimeoutError,
                    RuntimeError) as exc:
                status="UNAVAILABLE";error=type(exc).__name__
            latest=self.read(job_id)
            current=build_decision_projection(latest)
            current_digest=graph_context(
                current,build_offer_knowledge_graph(current))[1]
            if current_digest!=digest:
                status="STALE_AFTER_GRAPH_CHANGE";questions=[]
                retry=runs<MAX_RUNS
            with self._db() as db:
                db.execute("""UPDATE cart_graph_question_review
                    SET status=?,questions_json=?,error_type=?,updated_at=?
                    WHERE job_id=?""",
                    (status,json.dumps(questions,ensure_ascii=False),
                     error,datetime.now(timezone.utc).isoformat(),job_id))
            self.live_bus.signal(job_id)
        finally:
            with self._graph_question_lock:
                self._graph_question_pending.discard(job_id)
            if retry and not self.model_stop.is_set():
                self.schedule_graph_question_review(job_id)
