from pathlib import Path
import secrets
target = Path(__file__).resolve().parents[1] / ".env"
if target.exists():
    print(".env already exists; kept unchanged")
else:
    example = target.with_name(".env.example").read_text()
    target.write_text(example.replace("replace-with-a-local-password", secrets.token_urlsafe(18)))
    target.chmod(0o600)
    print("Created .env. Manager password is MANAGER_PASSWORD in this file.")

