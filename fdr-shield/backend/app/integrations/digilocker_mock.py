"""Demo DigiLocker/APAAR verification."""


async def verify_signatory(name: str, aadhaar_last4: str) -> dict:
    # Return {'verified': True, 'name': name} from static fixtures
    """Return deterministic demo registry fixtures; no external call is made."""
    return {'verified':len(aadhaar_last4)==4,'name':name,'issuer':'AICTE Demo DigiLocker'}
