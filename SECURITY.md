# Security

This alpha is a single-user application without login or tenant isolation.
Keep the HTTP listener on loopback and use SSH or a separately authenticated
private access layer. Do not expose it directly to the Internet.

Treat source documents and model output as untrusted input. Preserve exact
quote validation, revision checks and explicit human review boundaries.
Keep model logs, local environment files and Zotero write credentials private.

Report vulnerabilities through this repository's GitHub private vulnerability
reporting feature. Do not include secrets or private source documents in public
issues. There is no guaranteed response time during the alpha stage.
