import time

from app.admin_security import encrypt_mfa_secret, totp_code
from app.admin_security_models import AdminMfaCredential
from app.db import SessionLocal
from app.models import User

TEST_ADMIN_MFA_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def privileged_admin_headers(client, headers: dict, password: str = "Admin123!") -> dict:
    """Prepare the demo Admin for product-flow tests, then use the real reauth API.

    This is test fixture setup only. Runtime code never bypasses MFA: the helper
    seeds a known encrypted TOTP credential, then obtains privilege through the
    same password + TOTP endpoint used by the product.
    """
    with SessionLocal() as db:
        admin = db.query(User).filter(User.email == "admin@demo.nubagz.com").first()
        assert admin is not None
        credential = db.query(AdminMfaCredential).filter(AdminMfaCredential.user_id == admin.id).first()
        if not credential:
            credential = AdminMfaCredential(
                user_id=admin.id,
                secret_ciphertext=encrypt_mfa_secret(TEST_ADMIN_MFA_SECRET),
                enabled=True,
            )
            db.add(credential)
        else:
            credential.secret_ciphertext = encrypt_mfa_secret(TEST_ADMIN_MFA_SECRET)
            credential.enabled = True
            credential.disabled_at = None
        # Each test login represents a new ordinary session. Reset only the
        # test credential counter so the current authenticator code can seed
        # that session's privileged context deterministically.
        credential.last_counter = None
        db.commit()

    code = totp_code(TEST_ADMIN_MFA_SECRET, int(time.time() // 30))
    response = client.post(
        "/api/admin/security/privilege/start",
        headers=headers,
        json={"password": password, "code": code},
    )
    assert response.status_code == 200, response.text
    return {**headers, "X-NuBagz-Admin-Privilege": response.json()["privilege_token"]}
