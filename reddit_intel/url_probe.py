"""Optional HTTP probe for primary offer URLs (best-effort)."""

from __future__ import annotations

import urllib.error
import urllib.request


def probe_url_health(url: str, timeout: float = 4.0) -> tuple[bool | None, bool]:
    """Return (ok, timed_out). ok None if skipped or inconclusive."""
    u = (url or "").strip()
    if not u.lower().startswith("http"):
        return None, False
    req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "Mozilla/5.0 USAIntelProbe/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return (code is not None and int(code) < 400), False
    except urllib.error.HTTPError as e:
        return (200 <= e.code < 400), False
    except TimeoutError:
        return None, True
    except urllib.error.URLError as e:
        if "timed out" in str(e).lower():
            return None, True
        return False, False
    except Exception:
        return None, False
