"""Case store and state machine. The only code that writes cases (SystemDesign §5)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import threading
import time

from ghante_shared import config, db, models

from .bus import EventBus
from .clock import SimClock


class TransitionError(ValueError):
    pass


class NotFound(KeyError):
    pass


class CaseStore:
    def __init__(self, conn: sqlite3.Connection, bus: EventBus, clock: SimClock, deadline_hours: int = 72) -> None:
        self.conn, self.bus, self.clock, self.deadline_hours = conn, bus, clock, deadline_hours
        self._lock = threading.RLock()
        self._stats_at = 0.0
        self.scenario_info = lambda: {"state": "idle"}  # replaced by the scenario controller
        self.live_hero = True  # False in a headless run (HERO_SIM=1): the hero is then one more simulated farmer and is shown as such

    # ---------- events ----------
    def emit(self, type_: str, data: dict | None = None, *, case_id: str | None = None, agent: str = "system", live: bool | None = None) -> dict:
        if live is None:
            live = self._is_hero(case_id) if case_id else False
        return self.bus.publish(models.new_event(type_, data, case_id=case_id, agent=agent, live=live, sim_ts=self.clock.now_iso()))

    def _is_hero(self, case_id: str) -> bool:
        if not self.live_hero:
            return False
        row = self.conn.execute("SELECT is_hero FROM cases WHERE id = ?", (case_id,)).fetchone()
        return bool(row and row["is_hero"])

    # ---------- reads ----------
    def storm(self) -> dict | None:
        return db.row_to_dict(self.conn.execute("SELECT * FROM storm_event LIMIT 1").fetchone())

    def get(self, case_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise NotFound(case_id)
        case = db.row_to_dict(row)
        case["farmer"] = db.row_to_dict(self.conn.execute("SELECT * FROM farmer WHERE id = ?", (case["farmer_id"],)).fetchone())
        if case["farmer"]:
            case["farmer"].pop("sim", None)  # personas are for the simulator only
            case["village"] = db.row_to_dict(self.conn.execute("SELECT * FROM village WHERE id = ?", (case["farmer"]["village_id"],)).fetchone())
        case["policy"] = db.row_to_dict(self.conn.execute("SELECT * FROM policy WHERE id = ?", (case["policy_id"],)).fetchone())
        case["evidence"] = [db.row_to_dict(r) for r in self.conn.execute("SELECT * FROM evidence WHERE case_id = ? ORDER BY uploaded_at", (case_id,))]
        case["calls"] = [db.row_to_dict(r) for r in self.conn.execute("SELECT * FROM call WHERE case_id = ? ORDER BY attempt", (case_id,))]
        storm = self.storm()
        case["storm"] = {"id": storm["id"], "type": storm["type"], "started_at": storm["started_at"]} if storm else None
        return case

    def summaries(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT c.id, c.farmer_id, c.status, c.priority, c.deadline_at, c.attempts, c.is_hero, c.claim_ref, c.verdict, f.village_id,"
            " p.plot_lat AS lat, p.plot_lon AS lon FROM cases c JOIN farmer f ON f.id = c.farmer_id"
            " LEFT JOIN policy p ON p.id = c.policy_id ORDER BY c.id")
        out = [db.row_to_dict(r) for r in rows]
        if not self.live_hero:
            for c in out:
                c["is_hero"] = False
        return out

    def stats(self) -> dict:
        counts = {s: 0 for s in models.STATUSES}
        for row in self.conn.execute("SELECT status, COUNT(*) AS n FROM cases GROUP BY status"):
            counts[row["status"]] = row["n"]
        return {
            "affected": sum(counts.values()), "queued": counts[models.QUEUED] + counts[models.AFFECTED] + counts[models.NO_ANSWER],
            "in_call": counts[models.CALLING] + counts[models.IN_CALL],
            "in_progress": counts[models.EVIDENCE] + counts[models.PROCESSING] + counts[models.FILING],
            "filed": counts[models.FILED], "no_damage": counts[models.NO_DAMAGE], "escalated": counts[models.ESCALATED],
            "ineligible": counts[models.INELIGIBLE], "unreachable": counts[models.UNREACHABLE], "failed": counts[models.FAILED],
            "simulated": sum(counts.values()) - (self._live_cases() if self.live_hero else 0),
            "live": self._live_cases() if self.live_hero else 0,
        }

    def _live_cases(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM cases WHERE is_hero = 1").fetchone()["n"]

    def snapshot(self) -> dict:
        storm = self.storm()
        deadline = None
        if storm:
            deadline = (dt.datetime.fromisoformat(storm["started_at"]) + dt.timedelta(hours=self.deadline_hours)).isoformat()
        villages = [db.row_to_dict(r) for r in self.conn.execute("SELECT * FROM village ORDER BY id")]
        # every insured farm, so the map can show them before the storm (a farm's case id is "case_" + its farmer number)
        farms = [{"case_id": "case_" + r["id"][1:], "lat": r["plot_lat"], "lon": r["plot_lon"], "is_hero": bool(r["is_hero"]) and self.live_hero,
                  "village_id": r["village_id"]}
                 for r in self.conn.execute("SELECT f.id, f.is_hero, f.village_id, p.plot_lat, p.plot_lon FROM farmer f JOIN policy p ON p.farmer_id = f.id ORDER BY f.id")]
        return {"clock": self.clock.state(deadline), "stats": self.stats(), "storm": storm, "villages": villages, "cases": self.summaries(),
                "farms": farms, "scenario": self.scenario_info()}

    # ---------- writes ----------
    def open_case(self, farmer_id: str) -> dict:
        with self._lock:
            farmer = self.conn.execute("SELECT * FROM farmer WHERE id = ?", (farmer_id,)).fetchone()
            if farmer is None:
                raise NotFound(farmer_id)
            existing = self.conn.execute("SELECT id FROM cases WHERE farmer_id = ?", (farmer_id,)).fetchone()
            if existing:
                return self.get(existing["id"])
            storm = self.storm()
            if storm is None:
                raise NotFound("storm_event")
            policy = self.conn.execute("SELECT * FROM policy WHERE farmer_id = ?", (farmer_id,)).fetchone()
            deadline = (dt.datetime.fromisoformat(storm["started_at"]) + dt.timedelta(hours=self.deadline_hours)).isoformat()
            case_id = "case_" + farmer_id[1:]
            with self.conn:
                self.conn.execute(
                    "INSERT INTO cases (id, farmer_id, policy_id, storm_event_id, status, deadline_at, attempts, slots, opened_at, is_hero)"
                    " VALUES (?,?,?,?,?,?,0,?,?,?)",
                    (case_id, farmer_id, policy["id"] if policy else None, storm["id"], models.AFFECTED, deadline,
                     json.dumps(models.empty_slots()), self.clock.now_iso(), int(farmer["is_hero"])))
            self.emit("case.created", {"farmer_id": farmer_id, "village_id": farmer["village_id"],
                                       "lat": policy["plot_lat"] if policy else None, "lon": policy["plot_lon"] if policy else None,
                                       "deadline_at": deadline, "is_hero": bool(farmer["is_hero"]) and self.live_hero}, case_id=case_id, agent="dispatcher",
                      live=bool(farmer["is_hero"]) and self.live_hero)
            self.emit_stats()
            return self.get(case_id)

    def emit_stats(self, force: bool = False) -> None:
        """stats.updated at most four times a second: with 340 farmers the cases change far more often than anyone can read."""
        now = time.monotonic()
        if force or now - self._stats_at >= 0.25:
            self._stats_at = now
            self.emit("stats.updated", self.stats())

    def set_priority(self, case_id: str, priority: float) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE cases SET priority = ? WHERE id = ?", (priority, case_id))

    def persona(self, case_id: str) -> dict | None:
        """The scripted persona of a simulated farmer. Only the simulator may read it."""
        row = self.conn.execute("SELECT f.sim FROM cases c JOIN farmer f ON f.id = c.farmer_id WHERE c.id = ?", (case_id,)).fetchone()
        return json.loads(row["sim"]) if row and row["sim"] else None

    def status_of(self, case_id: str) -> str:
        row = self.conn.execute("SELECT status FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise NotFound(case_id)
        return row["status"]

    def statuses(self) -> dict[str, str]:
        return {r["id"]: r["status"] for r in self.conn.execute("SELECT id, status FROM cases")}

    def update_slots(self, case_id: str, partial: dict, agent: str = "intake", announce: bool = True) -> dict:
        clean = models.validate_slots(partial)
        with self._lock:
            row = self.conn.execute("SELECT slots FROM cases WHERE id = ?", (case_id,)).fetchone()
            if row is None:
                raise NotFound(case_id)
            slots = json.loads(row["slots"])
            changed = {k: v for k, v in clean.items() if slots.get(k) != v}
            slots.update(clean)
            with self.conn:
                self.conn.execute("UPDATE cases SET slots = ? WHERE id = ?", (json.dumps(slots, ensure_ascii=False), case_id))
        if announce:  # the simulator stores a whole persona at once and does not report it slot by slot
            for key, value in changed.items():
                self.emit("call.slot", {"slot": key, "value": value}, case_id=case_id, agent=agent)
        return slots

    def set_status(self, case_id: str, status: str, reason: str = "", agent: str = "system") -> dict:
        if status not in models.STATUSES:
            raise TransitionError(f"unknown status: {status}")
        with self._lock:
            row = self.conn.execute("SELECT status, attempts FROM cases WHERE id = ?", (case_id,)).fetchone()
            if row is None:
                raise NotFound(case_id)
            current = row["status"]
            if status not in models.TRANSITIONS[current]:
                raise TransitionError(f"{current} -> {status} is not allowed")
            if current == models.NO_ANSWER and status == models.QUEUED and row["attempts"] >= 3:
                raise TransitionError("three attempts already made: only UNREACHABLE is allowed")
            if current == models.NO_ANSWER and status == models.UNREACHABLE and row["attempts"] < 3:
                raise TransitionError("UNREACHABLE needs three attempts")
            attempts = row["attempts"] + 1 if status == models.CALLING else row["attempts"]
            with self.conn:
                self.conn.execute("UPDATE cases SET status = ?, attempts = ? WHERE id = ?", (status, attempts, case_id))
        self.emit("case.status_changed", {"from": current, "to": status, "reason": reason}, case_id=case_id, agent=agent)
        self.emit_stats()
        return {"id": case_id, "status": status, "attempts": attempts}

    # ---------- calls (SystemDesign §6: hero call, accept, decline, end) ----------
    def hero_farmer_id(self) -> str | None:
        row = self.conn.execute("SELECT id FROM farmer WHERE is_hero = 1 LIMIT 1").fetchone()
        return row["id"] if row else None

    def get_call(self, call_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM call WHERE id = ?", (call_id,)).fetchone()
        if row is None:
            raise NotFound(call_id)
        return db.row_to_dict(row)

    def place_call(self, case_id: str, reason: str = "dispatch") -> dict:
        """Ring the farmer. Moves the case to CALLING, or redials a call that dropped part-way (status stays as it is)."""
        with self._lock:
            row = self.conn.execute("SELECT status, attempts FROM cases WHERE id = ?", (case_id,)).fetchone()
            if row is None:
                raise NotFound(case_id)
            status = row["status"]
            if status in (models.IN_CALL, models.EVIDENCE):
                open_call = self.conn.execute("SELECT id FROM call WHERE case_id = ? AND ended_at IS NULL", (case_id,)).fetchone()
                if open_call:
                    raise TransitionError("a call for this case is already in progress")
                with self.conn:
                    self.conn.execute("UPDATE cases SET attempts = attempts + 1 WHERE id = ?", (case_id,))
            elif status in (models.AFFECTED, models.QUEUED, models.NO_ANSWER):
                if status in (models.AFFECTED, models.NO_ANSWER):
                    self.set_status(case_id, models.QUEUED, "queued for a call", agent="dispatcher")
                self.set_status(case_id, models.CALLING, reason, agent="dispatcher")
            else:
                raise TransitionError(f"a case in status {status} cannot be called")
            attempt = self.conn.execute("SELECT attempts FROM cases WHERE id = ?", (case_id,)).fetchone()["attempts"]
            call = {"id": f"call_{case_id.removeprefix('case_')}_{attempt}", "case_id": case_id, "attempt": attempt,
                    "room": f"case-{case_id}-{attempt}", "started_at": models.utc_now_iso(), "ended_at": None, "outcome": None}
            with self.conn:
                self.conn.execute("INSERT OR REPLACE INTO call (id, case_id, attempt, room, started_at, ended_at, outcome) VALUES (?,?,?,?,?,?,?)",
                                  tuple(call.values()))
        self.emit("call.started", {"call_id": call["id"], "attempt": attempt}, case_id=case_id, agent="dispatcher")
        return call

    def answer_call(self, call_id: str) -> dict:
        call = self.get_call(call_id)
        if call["ended_at"]:
            raise TransitionError("this call has already ended")
        status = self.conn.execute("SELECT status FROM cases WHERE id = ?", (call["case_id"],)).fetchone()["status"]
        if status == models.CALLING:
            self.set_status(call["case_id"], models.IN_CALL, "answered", agent="intake")
        return call

    def end_call(self, call_id: str, outcome: str) -> dict:
        """Close a call once. A second report of the same call (the phone and the agent both hang up) changes nothing."""
        if outcome not in models.CALL_OUTCOMES:
            raise ValueError(f"outcome must be one of {models.CALL_OUTCOMES}")
        with self._lock:
            call = self.get_call(call_id)
            if call["ended_at"]:
                return call
            ended = models.utc_now_iso()
            with self.conn:
                self.conn.execute("UPDATE call SET ended_at = ?, outcome = ? WHERE id = ?", (ended, outcome, call_id))
            call.update(ended_at=ended, outcome=outcome)
            status = self.conn.execute("SELECT status FROM cases WHERE id = ?", (call["case_id"],)).fetchone()["status"]
            if status == models.CALLING:  # never answered
                self.set_status(call["case_id"], models.NO_ANSWER, outcome, agent="dispatcher")
        started = dt.datetime.fromisoformat(call["started_at"].replace("Z", "+00:00"))
        duration = (dt.datetime.fromisoformat(ended.replace("Z", "+00:00")) - started).total_seconds()
        self.emit("call.ended", {"call_id": call_id, "outcome": outcome, "duration_s": round(duration, 1)}, case_id=call["case_id"], agent="intake")
        return call

    # ---------- evidence (SystemDesign §6: POST /api/cases/{id}/evidence) ----------
    def add_evidence(self, case_id: str, photo: bytes, meta: dict, suffix: str = ".jpg") -> dict:
        with self._lock:
            if self.conn.execute("SELECT 1 FROM cases WHERE id = ?", (case_id,)).fetchone() is None:
                raise NotFound(case_id)
            n = self.conn.execute("SELECT COUNT(*) AS n FROM evidence WHERE case_id = ?", (case_id,)).fetchone()["n"] + 1
            evidence_id = f"ev_{case_id.removeprefix('case_')}_{n}"
            folder = config.EVIDENCE_DIR / case_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{evidence_id}{suffix}"
            path.write_bytes(photo)
            sha = hashlib.sha256(photo).hexdigest()
            lat, lon, gps_source = meta.get("lat"), meta.get("lon"), meta.get("gps_source") or "phone"
            if lat is None or lon is None:
                # The phone had no GPS fix: record the insured plot's location and say so (SystemDesign §11).
                plot = self.conn.execute("SELECT p.plot_lat, p.plot_lon FROM cases c JOIN policy p ON p.id = c.policy_id WHERE c.id = ?", (case_id,)).fetchone()
                lat, lon, gps_source = (plot["plot_lat"], plot["plot_lon"], "plot") if plot else (None, None, "none")
            row = {"id": evidence_id, "case_id": case_id, "photo_path": str(path), "sha256": sha, "edge_label": meta.get("label"),
                   "edge_confidence": meta.get("confidence"), "edge_latency_ms": meta.get("latency_ms"), "edge_mode": meta.get("edge_mode"),
                   "lat": lat, "lon": lon, "gps_source": gps_source, "captured_at": meta.get("captured_at"), "uploaded_at": models.utc_now_iso(),
                   "captured_offline": int(bool(meta.get("captured_offline")))}
            with self.conn:
                self.conn.execute(f"INSERT INTO evidence ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))
        self.emit("evidence.received", {"evidence_id": evidence_id, "edge_label": row["edge_label"], "edge_confidence": row["edge_confidence"],
                                        "edge_latency_ms": row["edge_latency_ms"], "lat": row["lat"], "lon": row["lon"], "gps_source": row["gps_source"],
                                        "captured_offline": bool(row["captured_offline"]), "thumb_url": f"/api/evidence/{evidence_id}/photo"},
                  case_id=case_id, agent="evidence")
        return {"evidence_id": evidence_id, "sha256": sha}

    # ---------- claim pipeline (SystemDesign §13) ----------
    def latest_evidence(self, case_id: str) -> dict | None:
        return db.row_to_dict(self.conn.execute("SELECT * FROM evidence WHERE case_id = ? ORDER BY uploaded_at DESC, id DESC LIMIT 1", (case_id,)).fetchone())

    def save_pack(self, evidence_id: str, weather: dict | None, distance_m: float | None, loss_estimate_inr: float | None = None) -> None:
        """Evidence node: keep the weather record, the distance from the plot and the loss estimate with the photo."""
        with self._lock, self.conn:
            self.conn.execute("UPDATE evidence SET weather = ?, distance_from_plot_m = ?, loss_estimate_inr = ? WHERE id = ?",
                              (json.dumps(weather, ensure_ascii=False) if weather is not None else None, distance_m, loss_estimate_inr, evidence_id))

    def set_verdict(self, case_id: str, verdict: str, reasons: list[str]) -> None:
        if verdict not in models.VERDICTS:
            raise ValueError(f"verdict must be one of {models.VERDICTS}")
        with self._lock, self.conn:
            self.conn.execute("UPDATE cases SET verdict = ?, verdict_reasons = ? WHERE id = ?", (verdict, json.dumps(reasons, ensure_ascii=False), case_id))

    def first_call_started(self, case_id: str) -> str | None:
        row = self.conn.execute("SELECT started_at FROM call WHERE case_id = ? ORDER BY attempt LIMIT 1", (case_id,)).fetchone()
        return row["started_at"] if row else None

    def set_filed(self, case_id: str, claim_ref: str, filing_mode: str) -> dict:
        """Follow-up node: store the reference and close the case as FILED.

        time_to_file_s: for the live case, real seconds from the first ring to now (what the audience watched);
        for a simulated case, scenario seconds from the opening of the case to the scenario time of filing."""
        if filing_mode not in models.FILING_MODES:
            raise ValueError(f"filing_mode must be one of {models.FILING_MODES}")
        with self._lock:
            row = self.conn.execute("SELECT opened_at, is_hero FROM cases WHERE id = ?", (case_id,)).fetchone()
            if row is None:
                raise NotFound(case_id)
            filed_at = self.clock.now_iso()
            rang = self.first_call_started(case_id) if row["is_hero"] else None
            if rang:
                seconds = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(rang.replace("Z", "+00:00"))).total_seconds()
            else:
                seconds = (dt.datetime.fromisoformat(filed_at) - dt.datetime.fromisoformat(row["opened_at"])).total_seconds()
            seconds = round(max(0.0, seconds), 1)
            with self.conn:
                self.conn.execute("UPDATE cases SET claim_ref = ?, filing_mode = ?, filed_at = ?, time_to_file_s = ? WHERE id = ?",
                                  (claim_ref, filing_mode, filed_at, seconds, case_id))
            self.set_status(case_id, models.FILED, f"reference {claim_ref}", agent="followup")
        return {"claim_ref": claim_ref, "filing_mode": filing_mode, "filed_at": filed_at, "time_to_file_s": seconds}

    def add_sim_evidence(self, case_id: str, photo: dict, gps_offset_m: float) -> dict:
        """Simulator: the evidence a scripted persona "sends". There is no photo file; the row says it is simulated."""
        with self._lock:
            plot = self.conn.execute("SELECT p.plot_lat, p.plot_lon FROM cases c JOIN policy p ON p.id = c.policy_id WHERE c.id = ?", (case_id,)).fetchone()
            if plot is None:
                raise NotFound(case_id)
            n = self.conn.execute("SELECT COUNT(*) AS n FROM evidence WHERE case_id = ?", (case_id,)).fetchone()["n"] + 1
            evidence_id = f"ev_{case_id.removeprefix('case_')}_{n}"
            row = {"id": evidence_id, "case_id": case_id, "photo_path": None, "sha256": None, "edge_label": photo.get("label"),
                   "edge_confidence": photo.get("confidence"), "edge_latency_ms": None, "edge_mode": "simulated",
                   "lat": round(plot["plot_lat"] + gps_offset_m / 110574.0, 6), "lon": plot["plot_lon"], "gps_source": "simulated",
                   "captured_at": self.clock.now_iso(), "uploaded_at": models.utc_now_iso(), "captured_offline": 0}
            with self.conn:
                self.conn.execute(f"INSERT INTO evidence ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))
        self.emit("evidence.received", {"evidence_id": evidence_id, "edge_label": row["edge_label"], "edge_confidence": row["edge_confidence"],
                                        "edge_latency_ms": None, "lat": row["lat"], "lon": row["lon"], "gps_source": "simulated",
                                        "captured_offline": False, "thumb_url": None, "simulated": True}, case_id=case_id, agent="evidence")
        return {"evidence_id": evidence_id}

    def farmer_card(self, farmer_id: str) -> dict:
        """What the farmer's own phone may show about them: name and village. Nothing else."""
        row = self.conn.execute("SELECT f.id, f.name, v.name AS village FROM farmer f LEFT JOIN village v ON v.id = f.village_id WHERE f.id = ?",
                                (farmer_id,)).fetchone()
        if row is None:
            raise NotFound(farmer_id)
        return db.row_to_dict(row)

    def evidence_path(self, evidence_id: str) -> str:
        row = self.conn.execute("SELECT photo_path FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if row is None or not row["photo_path"]:  # a simulated farmer's evidence has no photo file
            raise NotFound(evidence_id)
        return row["photo_path"]

    def reset(self) -> dict:
        with self._lock:
            info = db.load_seed(self.conn)
            self.clock.reset()
        return info
