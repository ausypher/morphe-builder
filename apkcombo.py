#!/usr/bin/env python3
"""Download a matching APK variant from APKCombo for Morphe Builder."""
import os
import sys
import tempfile
import zipfile
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://apkcombo.app"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Referer": BASE + "/",
}


def session():
    s = requests.Session()
    retries = Retry(total=2, backoff_factor=1,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update(HEADERS)
    return s


def absolute(url):
    return urljoin(BASE + "/", url)


def version_page_url(base):
    return base.rstrip("/") + "/old-versions"


def select_version(soup, requested):
    table = soup.select_one(".list-versions")
    if table:
        wanted = requested.strip().removeprefix("v")
        for row in table.select(":scope > *"):
            name = row.select_one(".vername")
            link = row.select_one("a[href]")
            if name and link:
                actual = name.get_text(" ", strip=True)
                if actual.strip().removeprefix("v") == wanted:
                    return absolute(link["href"])
    # Same explicit-version URL format used by APKCombo Downloader.
    parts = base_parts = None
    return None


def is_universal(archs):
    valid = {"armeabi-v7a", "arm64-v8a", "x86", "x86_64"}
    normalized = {a.strip().lower() for a in archs}
    return normalized.issuperset(valid) or bool(normalized & {"universal", "noarch"})


def main():
    if len(sys.argv) != 6:
        raise SystemExit("usage: apkcombo.py BASE_URL VERSION OUTPUT ARCH DPI")
    base, version, output, arch, dpi = sys.argv[1:]
    base = base.rstrip("/")
    s = session()

    versions_url = version_page_url(base)
    response = s.get(versions_url, timeout=(15, 45))
    response.raise_for_status()
    version_soup = BeautifulSoup(response.text, "html.parser")
    variants_url = select_version(version_soup, version)
    if not variants_url:
        # Match the upstream tool's explicit-version URL pattern.
        org_repo = base.removeprefix(BASE + "/").strip("/")
        variants_url = absolute(f"{org_repo}/download/phone-{version.replace(' ', '-')}-apk")

    variants_response = s.get(variants_url, timeout=(15, 45), allow_redirects=True)
    variants_response.raise_for_status()
    if variants_response.history:
        # APKCombo can redirect directly when only one variant exists.
        selected_url = variants_response.url
    else:
        soup = BeautifulSoup(variants_response.text, "html.parser")
        table = soup.select_one("#best-variant-tab")
        if not table:
            raise RuntimeError("APKCombo did not return the variants table")

        variants = []
        for row in table.find_all(recursive=False):
            link = row.select_one("a[href]")
            if not link:
                continue
            label = row.select_one("span")
            label_text = label.get_text(" ", strip=True).upper() if label else ""
            if "APK" in label_text:
                kind = "apk"
            elif "BUNDLE" in label_text:
                kind = "bundle"
            else:
                continue
            arch_node = row.select_one(".blur")
            archs = (arch_node.get_text(strip=True).split(",")
                     if arch_node else [])
            specs = row.select(".spec")
            variant_dpi = specs[2].get_text(strip=True) if len(specs) > 2 else ""
            variants.append({
                "kind": kind,
                "archs": [a.strip() for a in archs],
                "dpi": variant_dpi,
                "url": absolute(link["href"]),
            })

        requested_arch = "armeabi-v7a" if arch == "arm-v7a" else arch
        arch_matches = [v for v in variants if requested_arch in v["archs"]]
        if requested_arch in ("all", "universal", "noarch"):
            arch_matches = [v for v in variants if is_universal(v["archs"])]
        elif not arch_matches:
            arch_matches = [v for v in variants if is_universal(v["archs"])]

        requested_dpi = dpi.strip()
        if requested_dpi and requested_dpi not in ("*", "any"):
            if requested_dpi.isdigit():
                requested_dpi += "dpi"
            arch_matches = [v for v in arch_matches
                            if v["dpi"].lower() == requested_dpi.lower()]

        candidates = [v for v in arch_matches if v["kind"] == "apk"]
        if not candidates:
            raise RuntimeError(
                f"No APK variant matches arch={arch}, dpi={dpi}, version={version}"
            )
        selected_url = candidates[0]["url"]

    checkin = s.get(BASE + "/checkin", timeout=(15, 30))
    checkin.raise_for_status()
    final_url = selected_url + "&" + checkin.text.strip()
    with s.get(final_url, timeout=(20, 180), stream=True) as download:
        download.raise_for_status()
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".apkcombo-", dir=os.path.dirname(output) or ".")
        try:
            with os.fdopen(fd, "wb") as out:
                for chunk in download.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        out.write(chunk)
            if os.path.getsize(temp_path) == 0 or not zipfile.is_zipfile(temp_path):
                raise RuntimeError("APKCombo response is empty or is not a valid APK/ZIP")
            os.replace(temp_path, output)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"APKCombo download failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
