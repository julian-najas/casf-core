# SDK Client Generation

CASF Verifier publishes its OpenAPI 3.1 schema at [`contracts/openapi.json`](../contracts/openapi.json).
You can use any OpenAPI code generator to produce a type-safe client in your language of choice.

## Python (recommended)

```bash
# Install the generator
pip install openapi-python-client

# Generate the SDK (output: sdk/python/)
make sdk
# — or manually —
openapi-python-client generate \
    --path contracts/openapi.json \
    --output-path sdk/python \
    --overwrite
```

The generated package is a fully-typed `httpx`-based client with Pydantic models.

### Usage

```python
from casf_verifier_client import Client
from casf_verifier_client.models import VerifyRequestV1

client = Client(base_url="http://localhost:8088")

response = client.verify_intent(
    body=VerifyRequestV1(
        request_id="...",
        tool="cliniccloud.list_appointments",
        mode="ALLOW",
        role="doctor",
        subject={"patient_id": "P-001"},
        args={},
        context={"tenant_id": "t-demo"},
    )
)
print(response.decision)  # ALLOW | DENY | NEEDS_APPROVAL
```

## TypeScript / JavaScript

```bash
npx @openapitools/openapi-generator-cli generate \
    -i contracts/openapi.json \
    -g typescript-fetch \
    -o sdk/typescript
```

## Go

```bash
docker run --rm -v "$PWD:/local" openapitools/openapi-generator-cli generate \
    -i /local/contracts/openapi.json \
    -g go \
    -o /local/sdk/go \
    --additional-properties packageName=casf
```

## Java / Kotlin

```bash
docker run --rm -v "$PWD:/local" openapitools/openapi-generator-cli generate \
    -i /local/contracts/openapi.json \
    -g kotlin \
    -o /local/sdk/kotlin
```

## C# / .NET

```bash
docker run --rm -v "$PWD:/local" openapitools/openapi-generator-cli generate \
    -i /local/contracts/openapi.json \
    -g csharp \
    -o /local/sdk/csharp
```

## Schema stability

The schema is **versioned** and checked in CI — any endpoint change triggers
a drift check (`make openapi-check`). Breaking changes require a version bump.

Generated SDKs are **not committed** to this repository. Consumers should
regenerate from `contracts/openapi.json` as part of their own build pipeline.
