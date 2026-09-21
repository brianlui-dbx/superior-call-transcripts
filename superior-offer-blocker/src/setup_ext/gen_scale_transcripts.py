# Databricks notebook source
# MAGIC %md
# MAGIC # [GENIE ONE DEMO — DATA SCALE-UP] Synthetic transcript & opportunity generator
# MAGIC
# MAGIC Makes the demo feel like a **real production environment** by generating an
# MAGIC abundant, realistic batch of call transcripts (and the matching Salesforce
# MAGIC opportunities) using the shipped 19-record sample as the style/schema reference.
# MAGIC
# MAGIC ### What it does (all keyed to the EXISTING pipeline contract)
# MAGIC 1. Generates `N_OPPS` synthetic **opportunities**, each with 1–3 **calls**, using
# MAGIC    templated propane-sales dialogue that reliably classifies into the 4A–4F
# MAGIC    offer-blocker codes (plus clean / no-blocker calls). Names, addresses, rates,
# MAGIC    fees, tank sizes vary per record (production feel; no two identical).
# MAGIC 2. Writes them as a JSON array file into the **landing Volume** so the existing
# MAGIC    Auto Loader ingests them incrementally alongside the original batch.
# MAGIC 3. Rebuilds `dim_salesforce_opportunity` as a **superset** — the original phones
# MAGIC    are preserved exactly (deterministic opp id), new phones are appended — so the
# MAGIC    inner phone-join in silver matches every generated call.
# MAGIC
# MAGIC ### Skew, not uniform (per the synthetic-data-gen skill)
# MAGIC * Blocker mix is **weighted** (4A rate objections prominent — this is a
# MAGIC   rate-strategy demo), not uniform.
# MAGIC * A **wounded cohort** of NY/NJ accounts carries degraded CX signals
# MAGIC   (long holds, abandons, low CSAT) so the contact-center domain has real
# MAGIC   variation and the churn-bomb cohort is rich.
# MAGIC * Multiple **teams/skills/agents** so CX analytics group into meaningful cuts.
# MAGIC * Stage mix includes a healthy share of **Closed Lost** (the reveal is about
# MAGIC   Closed Lost value) alongside Open / Closed Won.
# MAGIC
# MAGIC ### Additive & idempotent
# MAGIC Writes only a NEW landing file (`batch_scale_001.json`) and rebuilds
# MAGIC `dim_salesforce_opportunity` as a deterministic superset. Re-running reproduces
# MAGIC the same data. Does NOT alter any pipeline transformation or the ext objects.
# MAGIC
# MAGIC After running this, re-run:  base pipeline → ext setup (delivery seed) →
# MAGIC ext pipeline → metric-views job. Genie agents need no change.

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("n_opps", "300")
dbutils.widgets.text("seed", "42")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA  = dbutils.widgets.get("schema")
N_OPPS  = int(dbutils.widgets.get("n_opps"))
SEED    = int(dbutils.widgets.get("seed"))
assert CATALOG and SCHEMA, "catalog and schema are required (never defaulted)"

LANDING_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/landing/transcripts"
OUT_FILE    = f"{LANDING_DIR}/batch_scale_001.json"
FQ_OPP      = f"{CATALOG}.{SCHEMA}.dim_salesforce_opportunity"
print(f"CATALOG={CATALOG} SCHEMA={SCHEMA} N_OPPS={N_OPPS} SEED={SEED}")
print(f"OUT_FILE={OUT_FILE}")

# COMMAND ----------
import random, uuid, json, hashlib, re, os
from datetime import datetime, timedelta

rng = random.Random(SEED)

# ---- reference vocab (drawn from the shipped sample) ----------------------------
FIRST_NAMES = ["Beth","Abigail","Daniel","Marcus","Linda","Robert","Patricia","James",
    "Nancy","Frank","Denise","Harold","Susan","Gerald","Karen","Walter","Joyce","Ralph",
    "Diane","Eugene","Gloria","Arthur","Theresa","Roy","Judith","Carl","Evelyn","Louis",
    "Rosa","Vincent","Marilyn","Wayne","Doris","Roger","Janet","Keith","Ruth","Terry"]
LAST_NAMES = ["Ross","Stokes","Conner","Torres","Newman","Gonzalez","Harvey","Barry",
    "Brooks","Cain","Delgado","Frazier","Guerrero","Hoffman","Ingram","Jennings","Koch",
    "Lambert","Mercer","Nash","Osborne","Pratt","Quinn","Reeves","Sawyer","Tanner",
    "Underwood","Vaughn","Whitfield","Yates","Zimmerman","Boone","Cortez","Dunlap"]
STREETS = ["Elliott Ways","Lewis Hills","Route 17","Maple Ridge Rd","County Road 9",
    "Birchwood Ln","Old Mill Rd","Sycamore Ave","Harvest Way","Pinecrest Dr","Cedar Hollow",
    "Stonebridge Rd","Meadowbrook Ln","Valley View Dr","Route 9W","Hillcrest Ave"]

# NICE CXone org structure — several teams/skills/agents so CX analytics have variety.
TEAMS = ["US-Inside Sales","US-Retention","US-Field Sales","US-Customer Care"]
SKILLS = ["US-NY-New-Sales","US-NY-Sales-OB","US-NNE-New-Sales","US-Ntl-New-Sales",
    "US-NJ-New-Sales","US-NJ-Retention","US-NY-Retention","US-Care-Inbound"]
AGENTS = ["Robert Torres","Brian Conner","Elizabeth Newman","Jason Gonzalez",
    "Joshua Harvey MD","Todd Barry","Michael Brooks","Denise Cain","Sandra Pope",
    "Kevin Nash","Angela Reeves","Derek Sawyer","Monica Tanner","Paul Vaughn"]

# Area codes -> region (realistic assignment; region drives the silver filter).
NY_AREA = ["212","315","347","516","518","585","607","631","646","716","718","845","914","917","929"]
NJ_AREA = ["201","551","609","732","848","856","862","908","973"]
OUT_AREA = {"617":"Massachusetts","203":"Connecticut","416":"Ontario"}  # dropped by region filter

STAGES_WEIGHTED = (["Closed Lost"]*35 + ["Open"]*35 + ["Closed Won"]*30)

# ---- blocker archetypes: each returns (dialogue_turns, disposition_note) ----------
# Dialogue is realistic multi-turn propane sales conversation with clear, classifiable
# evidence for the target code. Values vary per call for production feel.

def _rate(lo, hi):  # per-gallon rate string
    return round(rng.uniform(lo, hi), 2)

def arch_4A(ctx):
    """Rate/price uncompetitive — customer compares quoted rate to competitor/current."""
    quoted = _rate(2.35, 3.15); comp = round(quoted - rng.uniform(0.25, 0.75), 2)
    who = rng.choice(["my current supplier","the company down the road","Ferrellgas","AmeriGas","the co-op"])
    turns = [
        ("AGENT", f"Thanks for calling Superior Plus residential propane, this is {ctx['agent'].split()[0]}, how can I help?"),
        ("CLIENT", f"I'm shopping propane for my home in {ctx['city']}. What's your per-gallon rate?"),
        ("AGENT", f"For your area we can do ${quoted:.2f} a gallon on a variable rate for the first year."),
        ("CLIENT", f"Whoa. {who.capitalize()} is charging me ${comp:.2f} a gallon right now. That's a big difference."),
        ("AGENT", "We do have reliability and service benefits, but I understand the rate is a factor."),
        ("CLIENT", f"It's the number that matters to me. At ${quoted:.2f} versus ${comp:.2f} I can't justify switching. That's too high."),
        ("AGENT", "I hear you. Let me note that the quoted rate is the sticking point."),
        ("CLIENT", "Yeah. Call me if the price comes down, otherwise I'm staying where I am."),
    ]
    return turns, f"Customer rejected quoted rate ${quoted:.2f}/gal vs {who} ${comp:.2f}/gal."

def arch_4B(ctx):
    """Ancillary fees barrier — rental / delivery / MUC pushback."""
    rent = rng.choice([15,18,20,22,25]); muc = rng.choice([90,120,150]); deliv = rng.choice([25,35,45])
    fee = rng.choice([
        ("tank rental", f"a monthly tank rental of ${rent} a month"),
        ("minimum use charge", f"a minimum use charge of ${muc} a year"),
        ("delivery fee", f"a per-delivery fee of ${deliv}")])
    turns = [
        ("AGENT", f"Thanks for calling Superior Plus, this is {ctx['agent'].split()[0]}."),
        ("CLIENT", f"I want to set up propane service at {ctx['addr']}."),
        ("AGENT", f"Great. The rate itself is fine, but there is also {fee[1]}."),
        ("CLIENT", f"Wait, {fee[0]}? On top of the gas? I only use a little propane for cooking."),
        ("AGENT", "It's standard on the leased-tank plan, yes."),
        ("CLIENT", f"That {fee[0]} makes the whole thing uneconomical for me. The gas price was fine, it's the extra charge I can't do."),
        ("AGENT", "Understood — so it's the fee, not the rate."),
        ("CLIENT", "Right. If you can waive that fee we can talk, otherwise it doesn't work."),
    ]
    return turns, f"Customer blocked on {fee[0]} (${rent}/{muc}/{deliv})."

def arch_4C(ctx):
    """Commercial model mismatch — wants ownership / pre-buy / fixed vs variable."""
    want = rng.choice([
        ("own their tank", "I want to own my tank, not rent it. I bought my last one outright."),
        ("pre-buy", "I want to pre-buy my gallons at a locked rate for the whole season."),
        ("fixed pricing", "I don't want a variable rate that moves with the market. I want a fixed price locked in.")])
    turns = [
        ("AGENT", f"Superior Plus, this is {ctx['agent'].split()[0]}, how can I help?"),
        ("CLIENT", f"Setting up service in {ctx['city']}. {want[1]}"),
        ("AGENT", "On our standard plan the tank is company-owned and the rate is variable."),
        ("CLIENT", f"That's not the deal I want. {want[1]}"),
        ("AGENT", "We don't really offer that structure for residential."),
        ("CLIENT", "Then we have a mismatch. The deal shape is the problem, not the price."),
        ("AGENT", "Noted — the commercial model is the blocker here."),
        ("CLIENT", "Correct. If you can't do it my way I'll go elsewhere."),
    ]
    return turns, f"Customer wanted {want[0]}; model mismatch."

def arch_4D(ctx):
    """Contract/transaction mechanics — auto-renewal / exit terms / credit check gating."""
    mech = rng.choice([
        ("auto-renewal", "It auto-renews every year unless I cancel in a narrow window? I don't like that."),
        ("early-termination fee", "There's an early-termination charge if I leave? That locks me in."),
        ("credit check", "You require a credit check before I can even get the rate? I'm not doing that.")])
    turns = [
        ("AGENT", f"Superior Plus residential, this is {ctx['agent'].split()[0]}."),
        ("CLIENT", "The rate and fees are actually fine. I just have a question on the agreement."),
        ("AGENT", "Sure — it's a three-year agreement with standard terms."),
        ("CLIENT", f"{mech[1]}"),
        ("AGENT", "That's part of the standard contract, yes."),
        ("CLIENT", f"The {mech[0]} is the problem. I'm okay with the deal itself, I'm not okay with that mechanic."),
        ("AGENT", "Understood — so it's the contract terms, not the pricing."),
        ("CLIENT", "Exactly. Fix that and I'll sign."),
    ]
    return turns, f"Customer blocked on {mech[0]}."

def arch_4E(ctx):
    """Availability/serviceability gap — out of area / tank size / timeline."""
    gap = rng.choice([
        ("service area", f"my address in {ctx['city']} is outside your delivery area"),
        ("tank size", "you can't service the 100-pound cylinder I already have"),
        ("timeline", "you can't install until eight weeks out and I need heat before winter")])
    turns = [
        ("AGENT", f"Superior Plus, this is {ctx['agent'].split()[0]}, how can I help?"),
        ("CLIENT", f"I'd like propane service at {ctx['addr']}."),
        ("AGENT", f"Let me check… unfortunately {gap[1]}."),
        ("CLIENT", "So you physically can't serve me?"),
        ("AGENT", f"Correct, that's a coverage/{gap[0]} limitation on our end."),
        ("CLIENT", "That's a shame, the price was good. But if you can't deliver it doesn't matter."),
        ("AGENT", "I'm sorry about that — it's an availability gap, not a pricing issue."),
        ("CLIENT", "Understood. I'll have to find someone who covers my area."),
    ]
    return turns, f"Serviceability gap: {gap[0]}."

def arch_4F(ctx):
    """Promotion ineligibility — referral / threshold / expired promo denied."""
    promo = rng.choice([
        ("referral credit", "My neighbor referred me and said I'd get a referral credit."),
        ("new-customer promo", "I saw your $200 new-customer credit advertised online."),
        ("volume discount", "Your site mentioned a volume discount for auto-delivery.")])
    turns = [
        ("AGENT", f"Superior Plus, this is {ctx['agent'].split()[0]}."),
        ("CLIENT", f"Setting up service. {promo[1]}"),
        ("AGENT", f"Let me check eligibility… unfortunately you don't qualify for the {promo[0]} in your situation."),
        ("CLIENT", f"But it was advertised. Why can't I get the {promo[0]}?"),
        ("AGENT", "The terms exclude your case, I'm sorry."),
        ("CLIENT", f"So the {promo[0]} I was counting on is off the table. That changes the math for me."),
        ("AGENT", "Understood — it's a promotion-eligibility issue."),
        ("CLIENT", "Yeah. I felt like I was promised something I can't actually get."),
    ]
    return turns, f"Denied {promo[0]}."

def arch_clean(ctx):
    """No blocker — benchmarking only, or concern resolved by rep explanation."""
    kind = rng.choice(["benchmark","resolved","admin"])
    if kind == "benchmark":
        turns = [
            ("AGENT", f"Superior Plus, this is {ctx['agent'].split()[0]}."),
            ("CLIENT", "Just price-checking a few suppliers, not switching today."),
            ("AGENT", "Happy to give you a quote for when you're ready."),
            ("CLIENT", "Appreciate it, just gathering info for now."),
            ("AGENT", "No problem, I'll note you're comparing options."),
            ("CLIENT", "Thanks, I'll call back if I decide to move."),
        ]
        note = "Benchmarking only; no switch intent."
    elif kind == "resolved":
        rate = _rate(2.3, 2.8)
        turns = [
            ("AGENT", f"Superior Plus, this is {ctx['agent'].split()[0]}."),
            ("CLIENT", f"I saw a variable rate — does that mean it can spike unpredictably?"),
            ("AGENT", f"It moves with the market, but historically it's around ${rate:.2f} and we cap swings. Here's how it works…"),
            ("CLIENT", "Oh, that actually makes sense. That's reasonable then."),
            ("AGENT", "Great, glad that cleared it up."),
            ("CLIENT", "Yeah, no concerns. Let's move forward."),
        ]
        note = "Concern resolved by rep explanation; offer not a barrier."
    else:
        turns = [
            ("AGENT", f"Superior Plus, this is {ctx['agent'].split()[0]}."),
            ("CLIENT", "I just need to change my scheduled delivery date."),
            ("AGENT", "Sure, I can move that for you. What date works?"),
            ("CLIENT", "Next Tuesday if possible."),
            ("AGENT", "Done — you're all set for Tuesday."),
            ("CLIENT", "Perfect, thank you."),
        ]
        note = "Routine service call (date change)."
    return turns, note

# Weighted blocker mix — 4A prominent (rate-strategy demo), clean calls present.
ARCH = [
    (arch_4A, 22), (arch_4B, 16), (arch_4C, 10), (arch_4D, 10),
    (arch_4E, 9),  (arch_4F, 8),  (arch_clean, 25),
]
ARCH_POOL = [fn for fn, w in ARCH for _ in range(w)]

# COMMAND ----------
# ---- generate opportunities & their calls ----------------------------------------
def normalize_phone(p):
    d = re.sub(r"\D", "", str(p))
    if len(d) >= 11: d = d[-10:]
    return d if len(d) == 10 else ""

def sf_opp_id(phone):  # SAME logic as src/setup/setup.py so ids are stable/compatible
    h = hashlib.md5(phone.encode()).hexdigest().upper()
    body = "".join(c for c in h if c.isalnum())[:8]
    return ("006Rg00000" + body)[:18].ljust(18, "0")

def make_phone():
    r = rng.random()
    if r < 0.06:  # ~6% out-of-region (proves the filter drops them)
        area = rng.choice(list(OUT_AREA.keys()))
    elif r < 0.60:
        area = rng.choice(NY_AREA)
    else:
        area = rng.choice(NJ_AREA)
    mid = rng.randint(200, 999); last = rng.randint(1000, 9999)
    return f"+1 ({area}) {mid}-{last}", area

def region_for_area(area):
    if area in OUT_AREA: return OUT_AREA[area]
    if area in NJ_AREA:  return "New Jersey"
    return "New York"

def interweave(turns):
    """Return the transcriptBlock list; keep clean multi-turn (classifies reliably)."""
    return [{"channelName": c, "text": t} for c, t in turns]

records = []
opp_rows = []
seen_phones = set()
base_dt = datetime(2026, 4, 1, 8, 0, 0)

i = 0
attempts = 0
while len([o for o in opp_rows]) < N_OPPS and attempts < N_OPPS * 5:
    attempts += 1
    phone, area = make_phone()
    p10 = normalize_phone(phone)
    if not p10 or p10 in seen_phones:
        continue
    seen_phones.add(p10)
    region = region_for_area(area)
    opp_id = sf_opp_id(p10)
    stage = rng.choice(STAGES_WEIGHTED)
    created = base_dt + timedelta(days=rng.randint(0, 45), hours=rng.randint(0, 8))

    # wounded cohort: NY/NJ accounts with degraded CX (skew, not uniform)
    wounded = (region in ("New York", "New Jersey")) and (rng.random() < 0.28)

    team = rng.choice(TEAMS); skill = rng.choice(SKILLS)
    n_calls = rng.choice([1, 1, 2, 2, 3])
    for seg in range(n_calls):
        arch_fn = rng.choice(ARCH_POOL)
        fn = rng.choice(FIRST_NAMES); ln = rng.choice(LAST_NAMES)
        ctx = {"agent": rng.choice(AGENTS), "city": region,
               "addr": f"{rng.randint(100,9999)} {rng.choice(STREETS)}"}
        turns, note = arch_fn(ctx)

        # ---- CXone operational metadata (skewed for wounded cohort) ----
        if wounded:
            hold = rng.choice([0, 0, 120, 240, 366, 480, 600])
            inq  = rng.choice([0, 30, 90, 180, 300])
            aband = 1 if rng.random() < 0.18 else 0
            csat_idx = rng.choice([0, 0, 2, 3, 4])                 # low CSAT index
            csat_sent = round(rng.uniform(-2.3, 0.6), 4)
        else:
            hold = rng.choice([0, 0, 0, 0, 20, 34, 60])
            inq  = rng.choice([0, 0, 0, 15, 30])
            aband = 0
            csat_idx = rng.choice([5, 5, 5, 6, 6])                 # healthy CSAT index
            csat_sent = round(rng.uniform(0.5, 4.2), 4)
        dur = sum(len(t[1].split()) for t in turns) * rng.randint(3, 6) + rng.randint(30, 120)
        aband_secs = rng.randint(5, 40) if aband else 0
        start = created + timedelta(days=seg * rng.randint(2, 12), hours=rng.randint(0, 9))

        rec = {
            "id": str(uuid.uuid4()),
            "clientPhoneNumber": phone,
            "clientAni": phone,
            "firstName": fn, "lastName": ln,
            "recordingStartTime": start.strftime("%Y-%m-%dT%H:%M:%S.") + f"{rng.randint(0,999):03d}Z",
            "startTime": start.strftime("%Y-%m-%dT%H:%M:%S.") + f"{rng.randint(0,999):03d}Z",
            "interactionDurationSeconds": dur,
            "totalDurationSeconds": dur + hold + aband_secs,
            "holdSeconds": hold, "holdCount": 1 if hold > 0 else 0,
            "inQueueSeconds": inq, "abandonSeconds": aband_secs, "abandoned": bool(aband),
            "acwSeconds": rng.randint(0, 60),
            "agentName": ctx["agent"], "teamName": team, "skillName": skill,
            "dispositionCode": "0", "dispositionNotes": note,
            "csatSentiment": csat_sent, "csatSentimentIndexScore": csat_idx,
            "mediaTypeName": "SCREEN", "outbound": bool(rng.random() < 0.3),
            "lang": "en", "langDialect": "en-US",
            "interwovenTranscript": {"transcriptBlock": interweave(turns)},
            "_synthetic_scale": True,
        }
        records.append(rec)

    opp_rows.append((p10, opp_id, stage, region, created.strftime("%Y-%m-%d %H:%M:%S")))

print(f"generated {len(records)} calls across {len(opp_rows)} opportunities")
from collections import Counter
print("region mix:", Counter(r[3] for r in opp_rows))
print("stage mix:", Counter(r[2] for r in opp_rows))

# COMMAND ----------
# ---- write transcript batch into the landing Volume -------------------------------
os.makedirs(LANDING_DIR, exist_ok=True)
with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(records, f)
print(f"wrote {OUT_FILE} ({os.path.getsize(OUT_FILE)} bytes, {len(records)} records)")

# COMMAND ----------
# ---- rebuild dim_salesforce_opportunity as a SUPERSET (preserve existing rows) ----
from pyspark.sql.types import StructType, StructField, StringType
from pyspark.sql import functions as F

sf_schema = StructType([
    StructField("contact_phone", StringType(), False),
    StructField("opportunity_id", StringType(), False),
    StructField("stage_name", StringType(), True),
    StructField("region", StringType(), True),
    StructField("created_datetime", StringType(), True),
])
new_df = (spark.createDataFrame(opp_rows, sf_schema)
          .withColumn("created_datetime", F.to_timestamp("created_datetime")))

# Union with existing rows (keep the original 19 exactly); dedupe on phone.
try:
    existing = spark.table(FQ_OPP)
    combined = existing.unionByName(new_df, allowMissingColumns=True)
except Exception as e:
    print("no existing dim (fresh):", e)
    combined = new_df

combined = combined.dropDuplicates(["contact_phone"])
combined.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(FQ_OPP)
n = spark.table(FQ_OPP).count()
print(f"dim_salesforce_opportunity now has {n} opportunities")
display(spark.sql(f"SELECT region, stage_name, COUNT(*) c FROM {FQ_OPP} GROUP BY region, stage_name ORDER BY region, stage_name"))
