"""
edgar_ingestor.py — Fetches SEC EDGAR filings for supply chain risk analysis.

Targets: 8-K (material events), 10-K/10-Q risk factors from key semiconductor companies.
Uses EDGAR full-text search API (no key required, fair-use policy applies).
Runs daily via Celery beat.
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta

import requests
from loguru import logger

from ingestion.base import Document, IngestStore

EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"

USER_AGENT = os.getenv(
    "EDGAR_USER_AGENT",
    "BDE-Research-Bot research@bde.local"
)

# CIK numbers for key semiconductor companies on SEC EDGAR
COMPANY_CIKS = {
    "NVIDIA":            "0001045810",
    "AMD":               "0000002488",
    "Intel":             "0000050863",
    "Qualcomm":          "0000804328",
    "Applied Materials": "0000796343",
    "Lam Research":      "0000707549",
    "KLA Corporation":   "0000319201",
    "Micron Technology": "0000723125",
    "Western Digital":   "0000106040",
    "Broadcom":          "0001730168",
    "Marvell Technology":"0001058057",
    "Entegris":          "0001101302",
    "Onto Innovation":   "0000074260",
    "Axcelis":           "0001113232",
    "Amkor Technology":  "0001047763",
    "GlobalFoundries":   "0001817662",
    "Tower Semiconductor":"0001062613",
    "Kulicke Soffa":     "0000056047",
}

SUPPLY_CHAIN_TERMS = [
    "supply chain", "shortage", "single source", "sole source",
    "concentration risk", "geopolitical", "export control", "EAR",
    "semiconductor", "foundry", "wafer", "packaging", "HBM",
    "Taiwan", "China", "TSMC", "ASML", "manufacturing capacity",
    "raw material", "critical material", "lead time",
]

IAS_TIER = 1
FORM_TYPES = ["8-K", "10-K", "10-Q"]


def _headers() -> dict:
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


def search_fulltext(query: str, days_back: int = 7) -> list[dict]:
    start = (date.today() - timedelta(days=days_back)).isoformat()
    params = {
        "q": f'"{query}"',
        "dateRange": "custom",
        "startdt": start,
        "forms": ",".join(FORM_TYPES),
        "_source": "file_date,period_of_report,entity_name,file_num,form_type,id",
        "hits.hits.total.value": 1,
        "hits.hits._source.period_of_report": 1,
    }
    try:
        resp = requests.get(EDGAR_SEARCH, params=params, headers=_headers(), timeout=20)
        resp.raise_for_status()
        return resp.json().get("hits", {}).get("hits", [])
    except Exception as e:
        logger.warning(f"EDGAR search '{query}': {e}")
        return []


def fetch_recent_filings(cik: str, company: str, days_back: int = 30) -> list[dict]:
    url = f"{EDGAR_SUBMISSIONS}/CIK{cik}.json"
    try:
        resp = requests.get(url, headers=_headers(), timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"EDGAR submissions {company} ({cik}): {e}")
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    descriptions = recent.get("primaryDocument", [])

    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    results = []
    for form, dt, acc, doc in zip(forms, dates, accessions, descriptions):
        if form not in FORM_TYPES:
            continue
        if dt < cutoff:
            break
        acc_clean = acc.replace("-", "")
        results.append({
            "company": company,
            "cik": cik,
            "form": form,
            "date": dt,
            "accession": acc,
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}",
            "index_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=5",
        })
    return results


def _extract_risk_snippet(filing: dict) -> str:
    try:
        resp = requests.get(filing["url"], headers=_headers(), timeout=20)
        text = resp.text
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        lower = text.lower()
        best = ""
        for term in SUPPLY_CHAIN_TERMS:
            idx = lower.find(term)
            if idx >= 0:
                snippet = text[max(0, idx - 200): idx + 500]
                if len(snippet) > len(best):
                    best = snippet
        return best[:3000] if best else text[:1000]
    except Exception:
        return f"{filing['company']} {filing['form']} {filing['date']}"


def run(days_back: int = 30) -> dict:
    store = IngestStore()
    total = 0

    for company, cik in COMPANY_CIKS.items():
        filings = fetch_recent_filings(cik, company, days_back=days_back)
        for filing in filings:
            uid = f"edgar:{filing['cik']}:{filing['accession']}"
            if store.is_known(uid):
                continue

            snippet = _extract_risk_snippet(filing)
            doc = Document(
                uid=uid,
                title=f"[{filing['form']}] {company} — {filing['date']}",
                text=snippet,
                url=filing["url"],
                source="edgar",
                ias_tier=IAS_TIER,
                published_at=f"{filing['date']}T00:00:00Z",
                metadata={
                    "company": company,
                    "cik": cik,
                    "form_type": filing["form"],
                    "accession": filing["accession"],
                },
            )
            if store.save(doc):
                total += 1
                logger.debug(f"EDGAR: {doc.title}")

    counts = store.counts()
    logger.info(f"EDGAR ingestor done. New: {total}. Queue: {counts}")
    return {"new": total, **counts}


if __name__ == "__main__":
    print(run())
