# ============================================================
# ULTRA-FAST BRONZE ENGINE (PARALLEL – 5 WORKERS)
# ============================================================

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
from datetime import datetime

_log_lock = threading.Lock()
_control_rows = []          # thread-safe collector for control records
_watermark_rows = []        # thread-safe collector for watermark records

def _safe_log(msg):
    with _log_lock:
        log(msg)

def _safe_append(entry):
    with _log_lock:
        run_log.append(entry)

def _collect_control(row):
    with _log_lock:
        _control_rows.append(row)

def _collect_watermark(row):
    with _log_lock:
        _watermark_rows.append(row)

# ---- Upper bound: current date at 00:00:00 (excludes today's data) ----
LOAD_DATE_TO = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

log("Starting Bronze Processing (Parallel – 5 workers)")
log(f"Date range: {LOAD_DATE_FROM}  <=  watermark  <  {LOAD_DATE_TO.strftime('%Y-%m-%d %H:%M:%S')}")


def process_table(r):
    """Process a single table config row – designed to run in a thread."""
    src = r["source_table"]
    tgt = r["target_table"]
    load_type = (r["load_type"] or "").upper()
    wm_col = r["watermark_column"]

    _safe_log(f"START | src={src} | tgt={tgt} | type={load_type} | wm_col={wm_col}")
    _safe_append((src, tgt, "STARTED", load_type))

    if tgt in SKIP_TARGETS:
        _safe_log(f"SKIPPED (explicit): {tgt}")
        _safe_append((src, tgt, "SKIPPED_EXPLICIT", load_type))
        return (tgt, "SKIPPED_EXPLICIT")

    if table_exists(tgt) and not is_delta_table_safe(tgt):
        _safe_log(f"SKIPPED (non-Delta target): {tgt}")
        _safe_append((src, tgt, "SKIPPED_NON_DELTA", load_type))
        return (tgt, "SKIPPED_NON_DELTA")

    # ------------------ READ SOURCE (with retry for transient 500s) ------------------
    MAX_RETRIES = 3
    RETRY_BACKOFF = [30, 90, 180]  # seconds between retries
    src_df = None

    for attempt in range(MAX_RETRIES):
        try:
            if "-" in src.split(".")[0]:
                parts = src.split(".")
                catalog_name, schema_name, table_name = parts
                src_safe = f"`{catalog_name}`.{schema_name}.{table_name}"
                src_df = spark.read.option("delta.sharing.ignoreStats", "true").table(src_safe)
            else:
                src_df = spark.read.option("delta.sharing.ignoreStats", "true").table(src)
            break  # success
        except Exception as e:
            err_str = str(e)
            if "500" in err_str or "INTERNAL_ERROR" in err_str:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF[attempt]
                    _safe_log(f"RETRY {attempt+1}/{MAX_RETRIES} for {src} after 500 error, waiting {wait}s...")
                    time.sleep(wait)
                    continue
            _safe_log(f"ERROR reading source: {err_str[:300]}")
            _safe_append((src, tgt, "READ_ERROR", load_type))
            return (tgt, "READ_ERROR")

    # ------------------ APPLY WATERMARK FILTER ------------------
    inc_df = src_df

    if wm_col and wm_col in src_df.columns:
        inc_df = inc_df.filter(F.col(wm_col) >= F.lit(LOAD_DATE_FROM))
        inc_df = inc_df.filter(F.col(wm_col) < F.lit(LOAD_DATE_TO))
        _safe_log(f"Date filter applied: {LOAD_DATE_FROM} <= {wm_col} < {LOAD_DATE_TO.strftime('%Y-%m-%d %H:%M:%S')}")

        if load_type != "OVERWRITE":
            last_wm = get_last_watermark(src, wm_col)
            if last_wm and last_wm > LOAD_DATE_FROM:
                inc_df = inc_df.filter(F.col(wm_col) >= F.lit(last_wm))
                _safe_log(f"Incremental watermark applied: {wm_col} >= {last_wm}")

    # ------------------ ADD AUDIT COLUMNS ------------------
    inc_df = (
        inc_df
        .withColumn("_ingest_timestamp", F.current_timestamp())
        .withColumn("_source_system", F.lit(src))
        .withColumn("_run_id", F.lit(RUN_ID))
    )

    # ------------------ WRITE ------------------
    if not table_exists(tgt):
        inc_df.limit(0).write.mode("overwrite").format("delta").saveAsTable(tgt)

    write_success = False
    for attempt in range(MAX_RETRIES):
        try:
            if load_type == "OVERWRITE":
                _safe_log(f"OVERWRITE → {tgt}")
                inc_df.write.mode("overwrite") \
                      .option("overwriteSchema", "true") \
                      .format("delta") \
                      .saveAsTable(tgt)
            else:
                _safe_log(f"APPEND → {tgt}")
                inc_df.write.mode("append") \
                      .format("delta") \
                      .saveAsTable(tgt)
            write_success = True
            break
        except Exception as e:
            err_str = str(e)
            if ("500" in err_str or "INTERNAL_ERROR" in err_str) and attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                _safe_log(f"RETRY {attempt+1}/{MAX_RETRIES} write for {tgt} after 500 error, waiting {wait}s...")
                time.sleep(wait)
                continue
            _safe_log(f"WRITE ERROR for {tgt}: {err_str[:300]}")
            _safe_append((src, tgt, "WRITE_ERROR", load_type))
            return (tgt, "WRITE_ERROR")

    if not write_success:
        _safe_append((src, tgt, "WRITE_ERROR", load_type))
        return (tgt, "WRITE_ERROR")

    _safe_log(f"SUCCESS → {tgt}")
    _safe_append((src, tgt, "SUCCESS", load_type))

    # =====================================================
    # COLLECT CONTROL + WATERMARK ROWS (written after all threads finish)
    # =====================================================
    now_ts = datetime.now()

    tgt_df = spark.read.table(tgt).persist()
    batch_df = tgt_df.filter(F.col("_run_id") == RUN_ID)

    incremental_count = batch_df.count()
    rows_written = incremental_count
    duplicate_rows = 0

    # ---------- COLLECT CONTROL ROW ----------
    _collect_control({
        "run_id": RUN_ID,
        "pipeline_name": PIPELINE_NAME,
        "source_table": src,
        "target_table": tgt,
        "src_count": incremental_count,
        "tgt_count": rows_written,
        "computed_at": now_ts,
        "layer": "BRONZE",
        "bronze_incremental_rows": incremental_count,
        "bronze_incremental_duplicate_rows": duplicate_rows,
        "silver_rows_written": None
    })

    # ---------- COLLECT WATERMARK ROW ----------
    if (
        incremental_count > 0
        and wm_col
        and wm_col in tgt_df.columns
    ):
        batch_max = batch_df.agg(F.max(F.col(wm_col))).collect()[0][0]

        if batch_max:
            _collect_watermark({
                "run_id": RUN_ID,
                "pipeline_name": PIPELINE_NAME,
                "source_table": src,
                "target_table": tgt,
                "watermark_column": wm_col,
                "watermark_value": str(batch_max),
                "processed_rows": rows_written,
                "processed_at": now_ts
            })

            _safe_log(f"Watermark collected for {tgt} → {batch_max}")
    else:
        _safe_log(f"Watermark NOT collected for {tgt}")

    tgt_df.unpersist()
    return (tgt, "SUCCESS")


# ============================================================
# DISPATCH – 5 parallel workers
# ============================================================
results = []

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {executor.submit(process_table, r): r["target_table"] for r in cfgs}

    for future in as_completed(futures):
        tgt_name = futures[future]
        try:
            result = future.result()
            results.append(result)
        except Exception as exc:
            _safe_log(f"EXCEPTION processing {tgt_name}: {str(exc)[:300]}")
            _safe_append(("?", tgt_name, "EXCEPTION", str(exc)[:100]))
            results.append((tgt_name, "EXCEPTION"))

log(f"\nBronze processing complete. {len(results)} tables processed.")

# ============================================================
# BATCH WRITE – control & watermark rows (single append each)
# ============================================================
if _control_rows:
    log(f"Writing {len(_control_rows)} control record(s) to {CONTROL_LOADS_MAT}")
    spark.createDataFrame(_control_rows, schema=CONTROL_SCHEMA) \
         .write.mode("append").saveAsTable(CONTROL_LOADS_MAT)
    log(f"Control records written successfully.")
else:
    log("No control records to write.")

if _watermark_rows:
    log(f"Writing {len(_watermark_rows)} watermark record(s) to {WATERMARK_STATE_TBL}")
    spark.createDataFrame(_watermark_rows, schema=WATERMARK_SCHEMA) \
         .write.mode("append").saveAsTable(WATERMARK_STATE_TBL)
    log(f"Watermark records written successfully.")
else:
    log("No watermark records to write.")

log("All done.")