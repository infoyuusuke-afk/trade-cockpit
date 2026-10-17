"""P0-32: independent review admission, never a substitute for actual review.

A PASS requires an APPROVED review from a different account, on the exact
current PR head SHA, without any later CHANGES_REQUESTED by that reviewer.
Do not trust the author, bots, comments, old commits or missing evidence.
Checks only GitHub metadata. No OWNER runtime, trading, Excel, or stop actions.
"""
import json
import os
import sys
import urllib.error
import urllib.request

def verdict(pr, reviews):
    try:
        author = pr["user"]["login"].casefold()
        head = pr["head"]["sha"]
        # Review receipt is valid on a Draft PR.  It never authorizes a merge,
        # cutover, stop, live order or marking the PR ready for review.
        if pr["merged"] is not False:
            return "BLOCKED_MERGED"
        if not isinstance(head, str) or len(head) != 40 or not all(c in "0123456789abcdef" for c in head):
            return "BLOCKED_HEAD"
        # The latest review by each account supersedes earlier reviews.
        # An approval of a prior HEAD never authorizes this HEAD.
        most_recent = {}
        for review in reviews:
            login = (review.get("user") or {}).get("login")
            if not isinstance(login, str) or not login or login.casefold() == author:
                continue
            if (review.get("user") or {}).get("type", "").lower() == "bot" or login.lower().endswith("[bot]"):
                continue
            timestamp = review.get("submitted_at")
            rid = review.get("id")
            if not timestamp or not isinstance(rid, int):
                continue
            key = login.casefold()
            stamp = (timestamp, rid)
            if key not in most_recent or stamp > most_recent[key][0]:
                most_recent[key] = (stamp, review)
        for _,review in most_recent.values():
            if review.get("state") == "APPROVED" and review.get("commit_id") == head:
                return "APPROVED_INDEPENDENT_CURRENT_HEAD"
        return "BLOCKED_NO_INDEPENDENT_CURRENT_HEAD_APPROVAL"
    except (KeyError, TypeError, AttributeError, ValueError):
        return "BLOCKED_UNVERIFIED"

def get_reviews(repo, number, token):
    url = "https://api.github.com/repos/" + repo + "/pulls/" + str(number) + "/reviews?per_page=100"
    if not token or not isinstance(number, int) or number < 1 or not isinstance(repo, str):
        raise ValueError("missing metadata")
    if repo.count("/") != 1 or any(not part.replace("-","").replace("_","").replace(".","").isalnum() for part in repo.split("/")):
        raise ValueError("invalid repository")
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "p0-32-review-gate",
    })
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise ValueError("review unavailable")
        data = json.load(response)
    if not isinstance(data,list) or len(data) >= 100:
        # Fail closed on pagination ambiguity, do not overlook later dismissals.
        raise ValueError("incomplete review list")
    return data

def main():
    try:
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
            event = json.load(f)
        pr = event["pull_request"]
        repo = event["repository"]["full_name"]
        number = pr["number"]
        reviews = get_reviews(repo, number, os.environ.get("GITHUB_TOKEN"))
        result = verdict(pr, reviews)
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError):
        result = "BLOCKED_UNVERIFIED"
    print("P0_32_REVIEW_ADMISSION=" + result, flush=True)
    print("P0_32_INDEPENDENT_REVIEW_REQUIRED=true", flush=True)
    print("P0_32_REVIEW_IS_NOT_DEPLOY_APPROVAL=true", flush=True)
    print("STOP_ALLOWED=false", flush=True)
    print("CUTOVER_ELIGIBLE=false", flush=True)
    print("REAL_SUBMIT_ALLOWED=false", flush=True)
    return 0 if result == "APPROVED_INDEPENDENT_CURRENT_HEAD" else 2

if __name__ == "__main__":
    sys.exit(main())
