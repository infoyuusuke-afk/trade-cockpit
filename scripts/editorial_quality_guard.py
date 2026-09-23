"""Editorial lint for internal Entertainment briefs. This is not an AI detector."""
from collections import Counter
CANNED=("three lessons","key takeaway","in conclusion","let's dive in","game changer")
def lint_briefs(briefs):
    issues=[]
    titles=[str(x.get("working_title","")).strip() for x in briefs]
    for title,count in Counter(titles).items():
        if title and count>1: issues.append({"code":"DUPLICATE_TITLE","value":title})
    openings=[]
    for i,b in enumerate(briefs):
        text=" ".join(str(x) for x in b.get("beats",[])).strip()
        low=(str(b.get("working_title",""))+" "+text).lower()
        for phrase in CANNED:
            if phrase in low: issues.append({"code":"CANNED_PHRASE","index":i,"value":phrase})
        opening=(text.split() or [""])[0].lower()
        openings.append(opening)
        if b.get("external_publish_allowed") is not False:
            issues.append({"code":"UNSAFE_PUBLICATION_STATE","index":i})
    for opening,count in Counter(openings).items():
        if opening and count>=3: issues.append({"code":"REPETITIVE_OPENING","value":opening})
    return issues
