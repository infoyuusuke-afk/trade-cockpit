"""Quality gate for Japan-market JP/Global internal briefs."""
REQUIRED_SECTIONS=("index_context","market_leaders","themes","notable_moves","unknowns")
def validate_brief(brief):
    errors=[]
    if brief.get("locale") not in ("ja-JP","en"): errors.append("INVALID_LOCALE")
    if brief.get("verified") is not True: errors.append("UNVERIFIED_INPUT")
    if brief.get("external_publish_allowed") is not False: errors.append("PUBLICATION_NOT_LOCKED")
    sections=brief.get("sections",{})
    for key in REQUIRED_SECTIONS:
        if key not in sections: errors.append("MISSING_"+key.upper())
    for claim in brief.get("claims",[]):
        if claim.get("type") not in ("OBSERVED","COMPUTED","ATTRIBUTED","INTERPRETATION","UNKNOWN"):
            errors.append("INVALID_CLAIM_TYPE")
        if claim.get("type") in ("OBSERVED","COMPUTED","ATTRIBUTED") and not claim.get("evidence_refs"):
            errors.append("CLAIM_WITHOUT_EVIDENCE")
    if brief.get("locale")=="en" and brief.get("literal_translation") is True:
        errors.append("GLOBAL_LITERAL_TRANSLATION_FORBIDDEN")
    return sorted(set(errors))
