"""
seed_sample_cases.py — Upload and index 3 railway/tram industry sample cases.

Run from project root:
    python -m scripts.seed_sample_cases
"""

from __future__ import annotations

import json
import logging
import os
import sys

from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv(override=True)

from backend.config import settings
from backend.infra.blob_storage import (
    BlobStorageClient,
    CaseRepository,
    CaseReadRepository,
)
from backend.infra.embeddings import EmbeddingClient
from backend.ingestion.case_ingestion import CaseIngestionService, CaseSearchIndex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CASE 1 — CLOSED  TRM-20250310-0001
# Pantograph carbon strip abnormal wear — Line 4 depot
# ─────────────────────────────────────────────────────────────────────────────

CASE_1 = {
    "case": {
        "case_number": "TRM-20250310-0001",
        "opening_date": "2025-03-10T07:30:00Z",
        "closure_date": "2025-04-02T15:00:00Z",
        "status": "closed",
    },
    "evidence": [],
    "phases": {
        "D1_D2": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-03-10T09:00:00Z",
                "last_updated": "2025-03-10T09:00:00Z",
            },
            "data": {
                "problem_description": (
                    "Pantograph carbon strips on Line 4 fleet (Citadis X05 units) are "
                    "showing accelerated wear rates after scheduled catenary maintenance "
                    "completed 2025-03-07. Average carbon strip lifespan has dropped from "
                    "~90,000 km to ~18,000 km. Visual inspection reveals deep gouging and "
                    "abnormal surface scoring on the carbon contact surface. Issue affects "
                    "all 6 vehicles that operate Line 4 out of Saint-Denis depot."
                ),
                "organization": {
                    "country": "France",
                    "site": "Saint-Denis Depot",
                    "department": "Fleet Maintenance — Traction & Pantograph Systems",
                },
                "team_members": [
                    "Isabelle Fontaine",
                    "Marc Delcourt",
                    "Pierre-Yves Renard",
                    "Amira Takouti",
                    "Gerard Vasseur",
                ],
            },
        },
        "D3": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-03-11T11:00:00Z",
                "last_updated": "2025-03-11T11:00:00Z",
            },
            "data": {
                "what_happened": (
                    "Following re-tensioning of catenary wire at sections KP 2.1 to KP 5.7 "
                    "on Line 4 (maintenance window 2025-03-07 06:00–12:00), all six "
                    "Citadis X05 vehicles reported abnormal pantograph wear within the first "
                    "30 operating hours post-maintenance. Carbon strips on affected vehicles "
                    "show deep longitudinal grooves and abnormal surface hardening. No sparking "
                    "reported by drivers. Strip wear rate measured at 4.8 mm per 1,000 km vs "
                    "normal baseline of 0.8 mm per 1,000 km."
                ),
                "why_problem": (
                    "Accelerated wear causes unplanned strip replacements, increases risk of "
                    "complete strip failure and arc damage to overhead catenary wire, leading "
                    "to service disruption on Line 4 which carries ~42,000 passengers daily. "
                    "Each unplanned strip replacement requires vehicle withdrawal and costs "
                    "approximately €1,400 per set including downtime."
                ),
                "when": "First excessive wear detected 2025-03-09 during routine morning "
                "inspection; full scope confirmed 2025-03-11 after measuring all 6 vehicles.",
                "where": "All 6 Line 4 Citadis X05 vehicles (TRM-401 to TRM-406), "
                "running on catenary section KP 0.0 – KP 12.4, Saint-Denis depot.",
                "who": "Identified by pantograph technician Marc Delcourt during scheduled "
                "100-hour inspection. Escalated to maintenance supervisor Isabelle Fontaine.",
                "how_identified": (
                    "Routine 100-hour pantograph inspection per maintenance plan MP-PAN-04. "
                    "Strip thickness measured with vernier caliper; wear rate calculated "
                    "against last replacement date and odometer. Anomaly confirmed by comparing "
                    "strip wear across all 6 Line 4 vehicles and two Line 7 vehicles as reference "
                    "(Line 7 catenary not serviced — normal wear observed on Line 7 vehicles)."
                ),
                "impact": (
                    "6 of 6 Line 4 vehicles affected. Estimated 3 vehicles require immediate "
                    "strip replacement within 48 hours if issue not resolved. Risk of catenary "
                    "damage if bare pantograph contact bar reaches wire. Service risk rating: HIGH. "
                    "Estimated cost if all 6 vehicles require emergency strip change: €8,400."
                ),
            },
        },
        "D4": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-03-11T14:00:00Z",
                "last_updated": "2025-03-11T14:00:00Z",
            },
            "data": {
                "actions": [
                    {
                        "action": (
                            "Immediate speed restriction imposed on Line 4: maximum 30 km/h "
                            "above KP 2.1 until catenary geometry re-verified."
                        ),
                        "responsible": "Isabelle Fontaine",
                        "due_date": "2025-03-11",
                        "actual_date": "2025-03-11",
                    },
                    {
                        "action": (
                            "Replace carbon strips on TRM-401, TRM-402, TRM-403 "
                            "(most severely worn, <2 mm remaining) with standard "
                            "SGL Carbon Grade 5 strips from depot stock."
                        ),
                        "responsible": "Marc Delcourt",
                        "due_date": "2025-03-12",
                        "actual_date": "2025-03-12",
                    },
                    {
                        "action": (
                            "Request catenary geometry survey of section KP 2.1–5.7 "
                            "by infrastructure team to measure wire height and stagger "
                            "against design spec (wire height 5,500 mm ± 50 mm)."
                        ),
                        "responsible": "Pierre-Yves Renard",
                        "due_date": "2025-03-12",
                        "actual_date": "2025-03-13",
                    },
                    {
                        "action": (
                            "Pull maintenance records for catenary re-tensioning work "
                            "completed 2025-03-07 and review tensioning values applied "
                            "vs design specification (contract reference INF-L4-CAT-2019)."
                        ),
                        "responsible": "Gerard Vasseur",
                        "due_date": "2025-03-12",
                        "actual_date": "2025-03-12",
                    },
                ],
            },
        },
        "D5": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-03-19T16:00:00Z",
                "last_updated": "2025-03-19T16:00:00Z",
            },
            "data": {
                "fishbone": {
                    "people": [
                        "Catenary maintenance contractor not briefed on wire height tolerance impact on pantographs",
                        "No pantograph specialist involved in catenary maintenance sign-off",
                        "Inspector who signed off tensioning work was not trained on tram-specific catenary specs",
                    ],
                    "environment": [
                        "Line 4 catenary section KP 2.1–5.7 has tighter geometry due to shared corridor with road traffic",
                        "Cold weather during maintenance (3°C) caused incomplete thermal expansion compensation",
                    ],
                    "process": [
                        "Catenary maintenance procedure does not specify wire height verification after re-tensioning for tram lines",
                        "No mandatory post-maintenance geometry check before returning line to service",
                        "No handshake process between catenary maintenance team and rolling stock maintenance team",
                    ],
                    "management": [
                        "Maintenance window shortened to 6 hours (from planned 9 hours) due to late engineering possession approval",
                        "Infrastructure contractor works to railway catenary standard, not tram-specific standard",
                    ],
                    "tools": [
                        "Catenary tension gauge used for re-tensioning does not compensate for tram pantograph contact force profile",
                        "No go/no-go gauge was used for post-tensioning wire height check",
                    ],
                    "place": [
                        "Wire height measured only at 3 points across the 3.6 km section — insufficient sampling density",
                    ],
                },
                "investigation_tasks": [
                    {
                        "task": "Catenary geometry survey — measure wire height at 20 m intervals KP 2.1–5.7",
                        "responsible": "Pierre-Yves Renard",
                        "due_date": "2025-03-13",
                        "actual_date": "2025-03-13",
                    },
                    {
                        "task": "Compare geometry survey results against design specification INF-L4-CAT-2019",
                        "responsible": "Gerard Vasseur",
                        "due_date": "2025-03-14",
                        "actual_date": "2025-03-14",
                    },
                    {
                        "task": "Reproduce wear on test rig at depot using measured wire height deviation and vehicle speed profile",
                        "responsible": "Marc Delcourt",
                        "due_date": "2025-03-17",
                        "actual_date": "2025-03-18",
                    },
                    {
                        "task": "Interview catenary contractor crew — review tensioning procedure and actual values applied",
                        "responsible": "Isabelle Fontaine",
                        "due_date": "2025-03-14",
                        "actual_date": "2025-03-14",
                    },
                    {
                        "task": "Check Line 7 and Line 2 catenary geometry for comparison (no wear reported on these lines)",
                        "responsible": "Amira Takouti",
                        "due_date": "2025-03-15",
                        "actual_date": "2025-03-15",
                    },
                ],
                "factors": [
                    {
                        "factor": "Wire height at KP 3.4 measured 5,420 mm — 130 mm below lower design tolerance (5,450 mm)",
                        "owner": "Pierre-Yves Renard",
                        "reviewed_date": "2025-03-14",
                        "status": "Confirmed root cause",
                    },
                    {
                        "factor": "Contractor re-tensioning log shows tension applied at 9.8 kN vs specified 8.5 kN for tram catenary",
                        "owner": "Gerard Vasseur",
                        "reviewed_date": "2025-03-14",
                        "status": "Confirmed contributing factor",
                    },
                    {
                        "factor": "Over-tensioning causes catenary wire to rise above design envelope at mid-span and drop below at tensioning points",
                        "owner": "Isabelle Fontaine",
                        "reviewed_date": "2025-03-15",
                        "status": "Confirmed mechanism",
                    },
                    {
                        "factor": "At speeds above 40 km/h, low wire height at KP 3.4 causes hard impact contact, not sliding contact — explains scoring pattern",
                        "owner": "Marc Delcourt",
                        "reviewed_date": "2025-03-18",
                        "status": "Confirmed by rig test",
                    },
                ],
                "five_whys": {
                    "A": [
                        "Why abnormal wear? — Hard intermittent contact at KP 3.4 instead of smooth sliding contact",
                        "Why hard contact? — Wire height 130 mm below design tolerance at that point",
                        "Why incorrect wire height? — Re-tensioning applied 9.8 kN instead of specified 8.5 kN",
                        "Why wrong tension value? — Contractor used railway standard tension spec, not tram-specific spec in contract INF-L4-CAT-2019",
                        "Why wrong spec used? — Maintenance order issued to contractor did not specify which tension specification to apply",
                    ],
                    "B": [
                        "Why was the error not caught before service resumed? — No post-maintenance geometry check procedure existed",
                        "Why no geometry check? — Existing catenary maintenance SOP did not require it for routine re-tensioning jobs",
                        "Why is SOP incomplete? — SOP was inherited from heavy rail practice; tram-specific requirements were not incorporated",
                        "Why were tram-specific requirements not incorporated? — Maintenance SOP last reviewed in 2018, before tram-specific EN 50367 amendment",
                        "Why was 2018 SOP still in use? — SOP review cycle is 5 years; last review was pre-amendment; next scheduled review 2023 was delayed",
                    ],
                },
            },
        },
        "D6": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-03-26T12:00:00Z",
                "last_updated": "2025-03-26T12:00:00Z",
            },
            "data": {
                "actions": [
                    {
                        "action": (
                            "Re-tension catenary section KP 2.1–5.7 to correct value of 8.5 kN "
                            "per specification INF-L4-CAT-2019. Verify wire height at 20 m intervals "
                            "post-tensioning using calibrated laser measurement system."
                        ),
                        "responsible": "Pierre-Yves Renard",
                        "due_date": "2025-03-21",
                        "actual_date": "2025-03-21",
                    },
                    {
                        "action": (
                            "Issue go/no-go gauge tool kit to catenary maintenance team. "
                            "Gauge set to 5,450–5,550 mm wire height tolerance. Gauge must "
                            "be applied at every tensioning point before line is returned to service."
                        ),
                        "responsible": "Isabelle Fontaine",
                        "due_date": "2025-03-20",
                        "actual_date": "2025-03-20",
                    },
                    {
                        "action": (
                            "Revise catenary maintenance SOP (document SOP-INF-CAT-003) to include: "
                            "(1) mandatory wire height verification at ≤50 m intervals after any "
                            "tensioning work; (2) go/no-go gauge check at all tensioning points; "
                            "(3) cross-sign-off from rolling stock maintenance supervisor before "
                            "returning line to service."
                        ),
                        "responsible": "Gerard Vasseur",
                        "due_date": "2025-03-28",
                        "actual_date": "2025-03-27",
                    },
                    {
                        "action": (
                            "Replace all carbon strips on TRM-401 through TRM-406 with new SGL Carbon "
                            "Grade 5 strips following catenary correction. Record baseline strip "
                            "thickness for all 6 vehicles to enable wear rate monitoring."
                        ),
                        "responsible": "Marc Delcourt",
                        "due_date": "2025-03-22",
                        "actual_date": "2025-03-22",
                    },
                    {
                        "action": (
                            "Add catenary-pantograph interface verification to contractor work order "
                            "template for all future catenary maintenance on tram lines. Include "
                            "reference to specification INF-L4-CAT-2019 Table 3 (tram-specific "
                            "tension values) and SOP-INF-CAT-003."
                        ),
                        "responsible": "Amira Takouti",
                        "due_date": "2025-03-25",
                        "actual_date": "2025-03-25",
                    },
                ],
            },
        },
        "D7": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-04-01T10:00:00Z",
                "last_updated": "2025-04-01T10:00:00Z",
            },
            "data": {
                "procedures_updated": True,
                "training_completed": True,
            },
        },
        "D8": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-04-02T15:00:00Z",
                "last_updated": "2025-04-02T15:00:00Z",
            },
            "data": {
                "quality_approved": True,
                "closure_date": "2025-04-02",
            },
        },
    },
    "ai": {
        "last_run": None,
        "summary": (
            "Root cause: catenary contractor applied railway-standard tension (9.8 kN) "
            "instead of tram-specific specification (8.5 kN) during re-tensioning of "
            "Line 4 section KP 2.1–5.7. This created a 130 mm wire height deficit at "
            "KP 3.4, causing hard pantograph impact at speeds >40 km/h and accelerating "
            "carbon strip wear 6x above baseline. Fix: re-tensioning to correct value, "
            "go/no-go gauge tool introduced, SOP revised with mandatory post-tensioning "
            "geometry check and cross-sign-off with rolling stock team."
        ),
        "identified_root_causes": [
            "Contractor applied railway-standard tension specification instead of tram-specific value",
            "No post-maintenance wire height verification procedure in existing catenary SOP",
            "Maintenance order to contractor did not specify tram-specific tension specification",
        ],
        "recommended_actions": [
            "All future catenary work orders on tram lines must reference tram-specific tension values",
            "Mandatory go/no-go gauge wire height check at all tensioning points before service return",
            "Rolling stock supervisor cross-sign-off required on all catenary maintenance clearances",
        ],
    },
    "meta": {
        "version": 1,
        "created_at": "2025-03-10T07:30:00Z",
        "updated_at": "2025-04-02T15:00:00Z",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CASE 2 — CLOSED  TRM-20250518-0002
# Bogie axle bearing overheating — Fleet X fleet wide
# ─────────────────────────────────────────────────────────────────────────────

CASE_2 = {
    "case": {
        "case_number": "TRM-20250518-0002",
        "opening_date": "2025-05-18T06:15:00Z",
        "closure_date": "2025-07-10T14:00:00Z",
        "status": "closed",
    },
    "evidence": [],
    "phases": {
        "D1_D2": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-05-18T10:00:00Z",
                "last_updated": "2025-05-18T10:00:00Z",
            },
            "data": {
                "problem_description": (
                    "Bearing temperature alarms triggered on 7 vehicles of Fleet X "
                    "(Alstom Urbalis-equipped Citadis 402 units, fleet numbers FX-201 to FX-231) "
                    "during peak summer service between 2025-05-15 and 2025-05-18. "
                    "Temperatures logged at 94–117°C on rear bogie axle bearings (positions B2L and B2R). "
                    "Alarm threshold is 90°C. No bearing failures to date but 3 vehicles withdrawn "
                    "from service as precaution. Issue coincides with return from scheduled PMS-45000 "
                    "maintenance cycle completed by depot team between 2025-04-28 and 2025-05-14."
                ),
                "organization": {
                    "country": "Belgium",
                    "site": "Brussels Anderlecht Depot",
                    "department": "Fleet Maintenance — Bogie & Running Gear",
                },
                "team_members": [
                    "Stefan Mertens",
                    "Nathalie Vanbrabant",
                    "Koen De Smedt",
                    "Luciana Rosetti",
                    "Thomas Jacobs",
                ],
            },
        },
        "D3": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-05-19T14:00:00Z",
                "last_updated": "2025-05-19T14:00:00Z",
            },
            "data": {
                "what_happened": (
                    "Between 2025-05-15 and 2025-05-18, bearing temperature alarms activated on "
                    "7 Fleet X vehicles during afternoon peak service (14:00–19:00, ambient 29–33°C). "
                    "All 7 vehicles had completed PMS-45000 maintenance within the previous 3 weeks. "
                    "Temperatures reached 94–117°C on rear bogie B2 axle bearings. ORBIS telemetry "
                    "logs show temperature rise beginning approximately 80 minutes after vehicle "
                    "departure from depot. FX-208 reached 117°C and was withdrawn immediately; "
                    "FX-214 and FX-221 reached 101°C and 98°C respectively."
                ),
                "why_problem": (
                    "Overheated bearings risk seizure and catastrophic axle failure leading to "
                    "derailment. At 117°C rated grease is above its drop point causing lubrication "
                    "film breakdown. Continued operation poses safety risk Category 1 (STIB-MIVB "
                    "safety classification). Fleet utilisation reduced by 3 vehicles during peak "
                    "service; passenger impact estimated 1,200 displaced journeys per day."
                ),
                "when": (
                    "First alarm 2025-05-15 14:42 on FX-208; pattern confirmed across 7 vehicles "
                    "by 2025-05-18; all affected vehicles had completed PMS-45000 in the "
                    "2025-04-28 to 2025-05-14 maintenance window."
                ),
                "where": (
                    "All 7 affected vehicles: Fleet X units FX-208, FX-214, FX-216, FX-221, "
                    "FX-224, FX-227, FX-231. Rear bogie only (B2 axle, both left and right bearings). "
                    "Front bogie bearings (B1) show normal temperatures. All operated from "
                    "Brussels Anderlecht Depot."
                ),
                "who": (
                    "Temperature alarms detected by ORBIS on-board monitoring and relayed to "
                    "control room. Control room notified depot maintenance supervisor Stefan Mertens. "
                    "Fault pattern identified by Nathalie Vanbrabant after reviewing ORBIS data for "
                    "all Fleet X vehicles."
                ),
                "how_identified": (
                    "ORBIS real-time telemetry — bearing temperature sensor channels BTB2L and BTB2R "
                    "exceeded 90°C threshold generating automatic alarm. Nathalie Vanbrabant cross-"
                    "referenced alarm time, affected vehicles, and recent maintenance history in CMMS "
                    "(Maximo) to identify the PMS-45000 correlation within 18 hours of first alarm."
                ),
                "impact": (
                    "Safety risk Category 1. 3 vehicles withdrawn from service. Bearing replacement "
                    "cost if required on all 7 vehicles: estimated €21,000 (€3,000 per bearing set x2 "
                    "per vehicle x7 vehicles). Service disruption during peak summer: 1,200 displaced "
                    "passenger journeys per day. Reputational risk if failure occurs in service."
                ),
            },
        },
        "D4": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-05-19T17:00:00Z",
                "last_updated": "2025-05-19T17:00:00Z",
            },
            "data": {
                "actions": [
                    {
                        "action": (
                            "Withdraw FX-208, FX-214, FX-221 from service immediately. "
                            "Cap service speed to 40 km/h for FX-216, FX-224, FX-227, FX-231 "
                            "with bearing temperature monitoring every 30 minutes."
                        ),
                        "responsible": "Stefan Mertens",
                        "due_date": "2025-05-18",
                        "actual_date": "2025-05-18",
                    },
                    {
                        "action": (
                            "Collect grease sample from rear bogie B2 bearing housing on each "
                            "of the 7 affected vehicles and 3 unaffected Fleet X vehicles as control. "
                            "Send samples to laboratory for grease specification analysis "
                            "(drop point, NLGI grade, base oil viscosity)."
                        ),
                        "responsible": "Koen De Smedt",
                        "due_date": "2025-05-20",
                        "actual_date": "2025-05-20",
                    },
                    {
                        "action": (
                            "Pull PMS-45000 workshop records for all 7 affected vehicles. "
                            "Identify grease batch/lot numbers used for rear bogie bearing regreasing. "
                            "Compare against specification requirement: SKF LGWA 2, NLGI grade 2, "
                            "drop point ≥260°C (per maintenance manual MM-BRG-45-REV4)."
                        ),
                        "responsible": "Nathalie Vanbrabant",
                        "due_date": "2025-05-20",
                        "actual_date": "2025-05-20",
                    },
                    {
                        "action": (
                            "Contact grease supplier (Lubrico NV) immediately: request confirmation "
                            "of product delivered in batch LUB-2025-0312 and review delivery note "
                            "against original purchase order PO-2025-1847."
                        ),
                        "responsible": "Thomas Jacobs",
                        "due_date": "2025-05-19",
                        "actual_date": "2025-05-19",
                    },
                ],
            },
        },
        "D5": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-05-30T15:00:00Z",
                "last_updated": "2025-05-30T15:00:00Z",
            },
            "data": {
                "fishbone": {
                    "people": [
                        "Goods receipt inspector did not verify grease specification against PO before signing in",
                        "PMS technician regreasing B2 bearings could not distinguish correct vs substituted grease by appearance",
                        "Supplier did not notify customer of product substitution",
                    ],
                    "environment": [
                        "High ambient temperature (29-33°C) during incident period accelerated thermal failure of under-spec grease",
                        "Summer peak service means longer continuous running hours per day than winter baseline",
                    ],
                    "process": [
                        "Incoming goods inspection procedure for lubricants does not require specification data sheet verification against PO",
                        "Grease containers not labelled with specification parameters — only product name, which was similar to correct product",
                        "No incoming test protocol to verify drop point or NLGI grade before stock admission",
                    ],
                    "management": [
                        "Supplier qualification process does not include notification obligation for equivalent product substitution",
                        "No approved equivalent product list maintained for critical maintenance consumables",
                    ],
                    "tools": [
                        "No portable drop-point measurement equipment available at depot goods receipt",
                        "CMMS does not cross-check consumable lot numbers against specification at time of goods receipt entry",
                    ],
                    "place": [
                        "Lubricant storage area: correct and substitute grease stored in adjacent bays with similar packaging",
                    ],
                },
                "investigation_tasks": [
                    {
                        "task": "Laboratory grease analysis — 7 affected + 3 control samples (drop point, NLGI grade, base oil viscosity)",
                        "responsible": "Koen De Smedt",
                        "due_date": "2025-05-23",
                        "actual_date": "2025-05-22",
                    },
                    {
                        "task": "Review delivery note batch LUB-2025-0312 vs PO-2025-1847: identify exactly what was delivered",
                        "responsible": "Thomas Jacobs",
                        "due_date": "2025-05-21",
                        "actual_date": "2025-05-21",
                    },
                    {
                        "task": "Inspect all Fleet X vehicles not yet showing alarms — check grease batch used during PMS-45000",
                        "responsible": "Nathalie Vanbrabant",
                        "due_date": "2025-05-22",
                        "actual_date": "2025-05-22",
                    },
                    {
                        "task": "Review incoming goods inspection records for batch LUB-2025-0312 — identify who signed off and what checks were performed",
                        "responsible": "Stefan Mertens",
                        "due_date": "2025-05-22",
                        "actual_date": "2025-05-23",
                    },
                    {
                        "task": "Check other open maintenance batches in depot for any other lubricant or consumable substitutions in same delivery",
                        "responsible": "Luciana Rosetti",
                        "due_date": "2025-05-24",
                        "actual_date": "2025-05-24",
                    },
                ],
                "factors": [
                    {
                        "factor": "Lab analysis confirmed: grease in affected vehicles is SKF LGFP 2 (food-grade, drop point 175°C) not SKF LGWA 2 (high-temp, drop point 260°C)",
                        "owner": "Koen De Smedt",
                        "reviewed_date": "2025-05-22",
                        "status": "Confirmed root cause",
                    },
                    {
                        "factor": "Delivery note for batch LUB-2025-0312 shows SKF LGFP 2 was delivered; PO-2025-1847 ordered SKF LGWA 2 — supplier made undisclosed substitution",
                        "owner": "Thomas Jacobs",
                        "reviewed_date": "2025-05-21",
                        "status": "Confirmed — supplier error, no prior notification",
                    },
                    {
                        "factor": "Goods receipt inspection only checked quantity and packaging condition — no specification verification against PO was performed",
                        "owner": "Stefan Mertens",
                        "reviewed_date": "2025-05-23",
                        "status": "Confirmed process gap",
                    },
                    {
                        "factor": "3 control vehicles serviced with correct grease from batch LUB-2025-0289 show normal bearing temperatures — confirms the grease as the sole variable",
                        "owner": "Nathalie Vanbrabant",
                        "reviewed_date": "2025-05-22",
                        "status": "Confirmed isolating factor",
                    },
                    {
                        "factor": "SKF LGFP 2 drop point 175°C exceeded at bearing temperatures 94-117°C, causing grease film breakdown and boundary lubrication failure",
                        "owner": "Koen De Smedt",
                        "reviewed_date": "2025-05-23",
                        "status": "Confirmed failure mechanism",
                    },
                ],
                "five_whys": {
                    "A": [
                        "Why bearing overheating? — Grease lubrication film failed above 175°C drop point",
                        "Why wrong drop point? — Wrong grease was applied: SKF LGFP 2 instead of SKF LGWA 2",
                        "Why wrong grease applied? — Supplier delivered SKF LGFP 2 against an order for SKF LGWA 2 without notification",
                        "Why substitution not caught on delivery? — Incoming goods inspection did not verify grease specification data sheet against purchase order",
                        "Why no specification check? — Lubricant incoming inspection SOP only requires quantity and packaging check, not specification verification",
                    ],
                    "B": [
                        "Why was the supplier substitution not notified? — Supplier qualification requirements did not mandate notification for equivalent product substitution",
                        "Why no notification mandate? — Supplier qualification process derived from standard ISO 9001 template; tram-critical consumables not identified as requiring enhanced supplier controls",
                        "Why no enhanced controls? — Critical consumables list in procurement only flags safety-critical components; lubricants not categorised as safety-critical",
                        "Why lubricants not safety-critical? — Classification was made when lubricant failures were assumed to be gradual and detectable — bearing temperature monitoring not available at that time",
                        "Why classification not updated? — Category review is triggered by supplier non-conformance reports; first NCR for lubricant substitution — no previous trigger",
                    ],
                },
            },
        },
        "D6": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-06-15T12:00:00Z",
                "last_updated": "2025-06-15T12:00:00Z",
            },
            "data": {
                "actions": [
                    {
                        "action": (
                            "Replace rear bogie B2 axle bearing grease on all 7 affected vehicles "
                            "(FX-208, 214, 216, 221, 224, 227, 231) with verified SKF LGWA 2 from "
                            "batch LUB-2025-0289. Record new grease quantity and batch number in CMMS."
                        ),
                        "responsible": "Koen De Smedt",
                        "due_date": "2025-05-30",
                        "actual_date": "2025-05-30",
                    },
                    {
                        "action": (
                            "Conduct bearing inspection (visual + vibration analysis) on all 7 "
                            "affected vehicles before return to full service. Confirm no bearing "
                            "damage from overheating event. Replace any bearing showing blueing, "
                            "pitting or elevated vibration signature."
                        ),
                        "responsible": "Stefan Mertens",
                        "due_date": "2025-06-02",
                        "actual_date": "2025-06-03",
                    },
                    {
                        "action": (
                            "Revise incoming goods inspection SOP (document SOP-PROC-ING-007) to add: "
                            "for lubricants and greases, mandatory verification of product data sheet "
                            "against PO specification before goods receipt sign-off. "
                            "Mandatory fields to verify: product name, NLGI grade, drop point, "
                            "base oil viscosity. Procedure effective immediately."
                        ),
                        "responsible": "Thomas Jacobs",
                        "due_date": "2025-06-10",
                        "actual_date": "2025-06-09",
                    },
                    {
                        "action": (
                            "Update supplier qualification requirements document (SQR-LUBRICO-001) "
                            "to include: (1) mandatory prior written notification for any product "
                            "substitution, even equivalent grade; (2) substitute product must be "
                            "approved in writing by depot maintenance manager before delivery accepted. "
                            "Re-qualify Lubrico NV under updated requirements."
                        ),
                        "responsible": "Luciana Rosetti",
                        "due_date": "2025-06-20",
                        "actual_date": "2025-06-18",
                    },
                    {
                        "action": (
                            "Classify all bearing lubricants and greases as Controlled Maintenance "
                            "Consumables in procurement system. Add specification verification "
                            "requirement to PO template for all lubricant orders."
                        ),
                        "responsible": "Nathalie Vanbrabant",
                        "due_date": "2025-06-15",
                        "actual_date": "2025-06-15",
                    },
                ],
            },
        },
        "D7": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-07-05T10:00:00Z",
                "last_updated": "2025-07-05T10:00:00Z",
            },
            "data": {
                "procedures_updated": True,
                "training_completed": True,
            },
        },
        "D8": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2025-07-10T14:00:00Z",
                "last_updated": "2025-07-10T14:00:00Z",
            },
            "data": {
                "quality_approved": True,
                "closure_date": "2025-07-10",
            },
        },
    },
    "ai": {
        "last_run": None,
        "summary": (
            "Root cause: supplier Lubrico NV delivered SKF LGFP 2 (drop point 175°C) "
            "as an undisclosed substitution for the ordered SKF LGWA 2 (drop point 260°C). "
            "The lower-rated grease failed under summer service temperatures on rear bogie "
            "B2 bearings across 7 Fleet X vehicles. Incoming goods inspection did not verify "
            "product specification versus purchase order. Fix: grease replacement, bearing "
            "inspection, incoming inspection SOP updated to require specification verification, "
            "supplier qualification requirements updated to mandate substitution notification."
        ),
        "identified_root_causes": [
            "Supplier delivered lower-temperature-rated SKF LGFP 2 as undisclosed substitution for SKF LGWA 2",
            "Incoming goods inspection SOP did not require specification verification for lubricants",
            "Supplier qualification requirements did not mandate notification for equivalent product substitution",
        ],
        "recommended_actions": [
            "Mandatory specification data sheet verification at goods receipt for all lubricants",
            "Supplier notification obligation for any product substitution before delivery",
            "Classify bearing lubricants as Controlled Maintenance Consumables in procurement",
        ],
    },
    "meta": {
        "version": 1,
        "created_at": "2025-05-18T06:15:00Z",
        "updated_at": "2025-07-10T14:00:00Z",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CASE 3 — OPEN   TRM-20260115-0003
# Door obstruction sensor false positives — Series B vehicles
# ─────────────────────────────────────────────────────────────────────────────

CASE_3 = {
    "case": {
        "case_number": "TRM-20260115-0003",
        "opening_date": "2026-01-15T08:00:00Z",
        "closure_date": None,
        "status": "open",
    },
    "evidence": [],
    "phases": {
        "D1_D2": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2026-01-15T10:30:00Z",
                "last_updated": "2026-01-15T10:30:00Z",
            },
            "data": {
                "problem_description": (
                    "Series B trams (Citadis X05 second batch, units SB-101 to SB-118) are "
                    "generating door obstruction fault codes (DCU fault F-0247: 'obstacle "
                    "detected — door hold') during normal passenger boarding at 3 stations: "
                    "Central Exchange, North Interchange, and Riverside. No physical obstruction "
                    "is present in any logged instance. The fault causes a 25–40 second door-hold "
                    "delay per event, increasing dwell time and cascading up to 3 minute service "
                    "delays. Fault began appearing 2025-12-18, 4 days after DCU software update "
                    "v2.4.7 was pushed fleet-wide to all Series B units. Series A units running "
                    "DCU v2.3.1 do not exhibit the fault."
                ),
                "organization": {
                    "country": "Netherlands",
                    "site": "Rotterdam Waalhaven Depot",
                    "department": "Fleet Maintenance — Doors & Passenger Systems",
                },
                "team_members": [
                    "Roos van den Berg",
                    "Jeroen Hofstede",
                    "Anita Brouwer",
                    "Lars Spiering",
                    "Elena Popescu",
                ],
            },
        },
        "D3": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2026-01-16T14:00:00Z",
                "last_updated": "2026-01-16T14:00:00Z",
            },
            "data": {
                "what_happened": (
                    "Since 2025-12-18, fault F-0247 'obstacle detected — door hold' is triggered "
                    "on Series B vehicles during boarding at Central Exchange (northbound platform 2), "
                    "North Interchange (all platforms), and Riverside (southbound platform 1). "
                    "Total fault events logged: 147 over 29 operating days. No physical obstruction "
                    "found in any case. DCU event logs show the fault is triggered by the infrared "
                    "light curtain sensor on door zones 2 and 3 (middle and rear of vehicle). "
                    "Fault absent on door zone 1 (driver cab end). Pattern is consistent across "
                    "at least 11 of the 18 Series B vehicles. Fault frequency is higher during "
                    "peak hours (07:00–09:00 and 17:00–19:30) and at stations with high passenger "
                    "density on the platform edge."
                ),
                "why_problem": (
                    "Each F-0247 fault event causes a 25–40 second forced door-hold, resulting in "
                    "dwell time exceeding the 55-second schedule allowance. This cascades to service "
                    "delays of up to 3 minutes per trip. With 147 events in 29 days, average delay "
                    "impact is approximately 73 minutes of cumulative passenger delay per day. "
                    "Additionally, driver workaround (manual override button) is required, increasing "
                    "driver workload and creating a safety concern: manual override bypasses the "
                    "obstruction detection intended to prevent door crush injuries."
                ),
                "when": (
                    "First event logged 2025-12-18 06:47 on unit SB-107 at Central Exchange. "
                    "DCU software v2.4.7 was pushed to all Series B units 2025-12-14 during "
                    "overnight maintenance window. Symptoms appeared 4 days after update. "
                    "Fault confirmed as ongoing as of 2026-01-15."
                ),
                "where": (
                    "Stations: Central Exchange (platform 2 northbound), North Interchange "
                    "(all 3 platforms), Riverside (platform 1 southbound). Vehicles: minimum "
                    "11 of 18 Series B units. Door zones: 2 and 3 only (infrared light curtain "
                    "sensors on middle and rear doors). Series A vehicles on same lines: no faults."
                ),
                "who": (
                    "Fault pattern first raised by driver team lead Erik van Houten to control room "
                    "2026-01-08 after noting repeated overrides at Central Exchange. Escalated to "
                    "Roos van den Berg (maintenance team lead) 2026-01-10. Case opened formally "
                    "2026-01-15 after fault count exceeded threshold for 8D investigation."
                ),
                "how_identified": (
                    "Driver manual override logs cross-referenced with TETRA (on-board diagnostic "
                    "system) fault codes by Jeroen Hofstede. TETRA data extraction confirmed "
                    "F-0247 correlation with DCU v2.4.7 rollout date. Comparison with Series A "
                    "vehicles (DCU v2.3.1, zero F-0247 faults) identifies software version as "
                    "primary differentiating factor."
                ),
                "impact": (
                    "Service punctuality impact: 147 events in 29 days causing ~73 minutes "
                    "cumulative passenger delay per day on Lines 12 and 23. Driver workload "
                    "increase from manual override requirement. Safety concern: systematic use "
                    "of manual override bypasses obstruction protection — risk classified as "
                    "medium per RAMS assessment. Passenger complaint rate up 34% since December."
                ),
            },
        },
        "D4": {
            "header": {
                "completed": True,
                "status": "confirmed",
                "confirmed_at": "2026-01-17T11:00:00Z",
                "last_updated": "2026-01-17T11:00:00Z",
            },
            "data": {
                "actions": [
                    {
                        "action": (
                            "Implement manual door override protocol at Central Exchange, "
                            "North Interchange, and Riverside: drivers authorised to use "
                            "manual override for F-0247 faults at these stations. "
                            "Override event must be logged via TETRA driver input. "
                            "Safety briefing issued to all Series B drivers by 2026-01-17."
                        ),
                        "responsible": "Roos van den Berg",
                        "due_date": "2026-01-17",
                        "actual_date": "2026-01-17",
                    },
                    {
                        "action": (
                            "Increase platform supervision at Central Exchange platform 2 "
                            "and North Interchange during peak hours (07:00–09:00, 17:00–19:30) "
                            "until root cause resolved. Station staff to observe door zone 2 "
                            "and 3 sensor areas during boarding."
                        ),
                        "responsible": "Lars Spiering",
                        "due_date": "2026-01-18",
                        "actual_date": "2026-01-18",
                    },
                    {
                        "action": (
                            "Extract TETRA F-0247 event logs and sensor raw data for all "
                            "Series B vehicles for period 2025-12-14 to 2026-01-15. "
                            "Send to Alstom DCU engineering team for software analysis. "
                            "Include comparison dataset from Series A vehicles (DCU v2.3.1)."
                        ),
                        "responsible": "Jeroen Hofstede",
                        "due_date": "2026-01-20",
                        "actual_date": "2026-01-19",
                    },
                    {
                        "action": (
                            "Rollback DCU software to v2.3.1 on 2 Series B test vehicles "
                            "(SB-103 and SB-111) to confirm v2.4.7 as the causal factor. "
                            "Monitor for 5 operating days and compare fault frequency."
                        ),
                        "responsible": "Elena Popescu",
                        "due_date": "2026-01-22",
                        "actual_date": "2026-01-21",
                    },
                ],
            },
        },
        "D5": {
            "header": {
                "completed": False,
                "status": "not_started",
                "confirmed_at": None,
                "last_updated": None,
            },
            "data": {},
        },
        "D6": {
            "header": {
                "completed": False,
                "status": "not_started",
                "confirmed_at": None,
                "last_updated": None,
            },
            "data": {},
        },
        "D7": {
            "header": {
                "completed": False,
                "status": "not_started",
                "confirmed_at": None,
                "last_updated": None,
            },
            "data": {},
        },
        "D8": {
            "header": {
                "completed": False,
                "status": "not_started",
                "confirmed_at": None,
                "last_updated": None,
            },
            "data": {},
        },
    },
    "ai": {
        "last_run": None,
        "summary": "",
        "identified_root_causes": [],
        "recommended_actions": [],
    },
    "meta": {
        "version": 1,
        "created_at": "2026-01-15T08:00:00Z",
        "updated_at": "2026-01-17T11:00:00Z",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Upload + Index
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    blob_client = BlobStorageClient(
        settings.AZURE_STORAGE_CONNECTION_STRING,
        settings.AZURE_STORAGE_CONTAINER,
    )
    case_repo = CaseRepository(blob_client)
    case_read_repo = CaseReadRepository(
        settings.AZURE_STORAGE_CONNECTION_STRING,
        settings.AZURE_STORAGE_CONTAINER,
    )
    search_index = CaseSearchIndex(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        index_name=settings.CASE_INDEX_NAME or "case_index_v3",
        admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
    )
    embedding_client = EmbeddingClient()
    ingestion_service = CaseIngestionService(
        search_index=search_index,
        case_repository=case_read_repo,
        embedding_client=embedding_client,
        logger=logger,
    )

    cases = [
        ("TRM-20250310-0001", CASE_1, "closed"),
        ("TRM-20250518-0002", CASE_2, "closed"),
        ("TRM-20260115-0003", CASE_3, "open"),
    ]

    for case_id, doc, case_type in cases:
        blob_path = f"{case_id}/case.json"
        logger.info("──────────────────────────────────────────")
        logger.info("Processing %s (%s)", case_id, case_type)

        # Upload to blob storage (overwrite=True in case re-running)
        blob_client.upload_json(blob_path, json.dumps(doc, indent=2), overwrite=True)
        logger.info("BLOB UPLOAD OK  path=%s", blob_path)

        # Index in Azure AI Search
        if case_type == "closed":
            ingestion_service.ingest_closed_case(case_id)
        else:
            ingestion_service.index_open_case(case_id)

    logger.info("──────────────────────────────────────────")
    logger.info("All 3 cases uploaded and indexed.")


if __name__ == "__main__":
    main()
