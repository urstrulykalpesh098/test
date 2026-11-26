"""Shared helpers for the Eye View trackers (credit, policy). Standard library only."""
import os, statistics as st, time, urllib.error, urllib.request

UA = "eyeview-desk/1.0 (research script)"  # FRED stalls on browser-like agents
# SEC asks automated clients for a descriptive User-Agent with a contact address. Set SEC_USER_AGENT to your own.
SEC_UA = os.environ.get("SEC_USER_AGENT", "research-script admin@example.org")


def get(url, timeout=40, tries=3, ua=UA):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tries - 1: raise
        except urllib.error.URLError:
            if i == tries - 1: raise
        time.sleep(2 * (i + 1))


def pctile(x, xs):
    xs = [v for v in xs if v is not None]
    return round(100 * sum(v <= x for v in xs) / len(xs)) if xs and x is not None else None


def zscore(x, xs):
    xs = [v for v in xs if v is not None]
    if x is None or len(xs) < 10: return None
    sd = st.pstdev(xs)
    return round((x - st.mean(xs)) / sd, 2) if sd else None
