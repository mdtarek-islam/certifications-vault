<p align="center"><img src="./docs/readme-cover-img.webp" alt="Certifications Vault cover" width="100%"></p>

# Certifications Vault

A personal vault of PDF certificates and completion badges, indexed by issuer, domain and date.

## Overview

This repository stores the PDF certificates and completion badges earned by Md Tarek Islam. It contains no software.

<!-- CERTS-COUNT:START -->
It holds 11 documents from 2 issuers, completed between 15 and 17 October 2026.

| Issuer | Documents | Completed |
|---|---|---|
| AWS | 6 | 17 Oct 2026 |
| Claude Academy | 5 | 15 to 16 Oct 2026 |
<!-- CERTS-COUNT:END -->

## Architecture

![Architecture](./assets/architecture.svg)

The diagram maps the vault in three columns. A script regenerates it from the files.

1. Domain: each certificate maps to one domain, such as Cloud or Machine learning.
2. Issuer: lines join each domain to the issuers that hold certificates in it. Numbers on the lines count certificates.
3. Count: each issuer shows its total number of certificates.

![Pipeline flow](./assets/pipeline-flow.svg)

The second diagram shows the steps to add a certificate to the vault.

## Features

### Certificate index

<!-- CERTS:START -->
| # | Title | Issuer | Domain | Completed | Document | Verify |
|---|---|---|---|---|---|---|
| 1 | AWS Billing and Cost Management | AWS | Cloud | 17 Oct 2026 | [PDF](./AWS%20-%20Billing%20and%20Cost%20Management.pdf) | See document |
| 2 | Fundamentals of Machine Learning and Artificial Intelligence | AWS | Machine learning | 17 Oct 2026 | [PDF](./AWS%20-%20Fundamentals%20of%20Machine%20Learning.pdf) | See document |
| 3 | Fundamentals of Prompt Engineering with Claude | AWS | Generative AI | 17 Oct 2026 | [PDF](./AWS%20-%20Fundamentals%20of%20Prompt%20Engineering%20with%20Claude.pdf) | See document |
| 4 | Introduction to Claude Platform on AWS | AWS | AI tooling | 17 Oct 2026 | [PDF](./AWS%20-%20Introduction%20to%20Claude%20Platform%20on%20AWS.pdf) | See document |
| 5 | Introduction to Generative AI: Art of the Possible | AWS | Generative AI | 17 Oct 2026 | [PDF](./AWS%20-%20Introduction%20to%20Generative%20AI%20-%20Art%20of%20the%20Possible.pdf) | See document |
| 6 | Job Roles in the Cloud | AWS | Cloud | 17 Oct 2026 | [PDF](./AWS%20-%20Job%20Roles%20in%20the%20Cloud.pdf) | See document |
| 7 | Claude 101 | Claude Academy | AI tooling | 15 Oct 2026 | [PDF](./CLAUDE%20ACADEMY%20-%20Claude%20101.pdf) | [Verify](https://academy.claude.com/verify/35734aed9d946c2bcf04142d81f72c80) |
| 8 | Claude Code 101 | Claude Academy | AI tooling | 15 Oct 2026 | [PDF](./CLAUDE%20ACADEMY%20-%20Claude%20Code%20101.pdf) | [Verify](https://academy.claude.com/verify/f3429b2c413ef3b1cbf0316be64b62fa) |
| 9 | AI capabilities and limitations | Claude Academy | Generative AI | 16 Oct 2026 | [PDF](./CLAUDE%20ACADEMY%20-%20AI%20Capabilities%20and%20Limitations.pdf) | [Verify](https://academy.claude.com/verify/b568951506af1f595bf62a845933b65d) |
| 10 | AI Fluency: Framework and foundations | Claude Academy | Generative AI | 16 Oct 2026 | [PDF](./CLAUDE%20ACADEMY%20-%20AI%20Fluency%20Framework%20Foundations.pdf) | [Verify](https://academy.claude.com/verify/aa0fddd2f7ab5515d59de5722cd4d8f2) |
| 11 | Claude Code in action | Claude Academy | AI tooling | 16 Oct 2026 | [PDF](./CLAUDE%20ACADEMY%20-%20Claude%20Code%20in%20Action.pdf) | [Verify](https://academy.claude.com/verify/9dfc136a80ea983955109f4a35fc79b9) |
<!-- CERTS:END -->

### Engineering findings

1. The AWS certificates print 17 October 2026 as the completion date.
2. The Claude Academy dates come from the issue metadata of each PDF.
3. Claude Academy badges carry a public verification link. The AWS PDFs carry no link in this index, so check the document itself.

## Quick start

1. Clone the repository: `git clone https://github.com/mdtarek-islam/certifications-vault.git`
2. Open any PDF from the index with a PDF viewer.
3. For a Claude Academy badge, open its Verify link in a browser.
4. For an AWS certificate, read the details printed on the PDF.

## Configuration

No configuration needed.

## Usage

Add a new certificate in 3 steps.

1. Name the file `ISSUER - Title.pdf`, for example `AWS - Job Roles in the Cloud.pdf`. Use `CLAUDE ACADEMY` for Claude Academy badges.
2. Place the file in the repository root, or in a folder named after the issuer.
3. Run `python scripts/sync_certificates.py`. It rewrites the index, the diagram and the tables in this README.

The `--check` flag exits with 1 when outputs are stale. The `--dry-run` flag lists changes and writes nothing.
To fix a field, add an entry keyed by the file SHA-256 to `docs/certificates-overrides.json`. The script never rewrites that file.

A GitHub Actions workflow runs the script daily at 00:00 UTC and commits only when the output changes.

## Licence and contribution

The repository is proprietary. All rights reserved. See [LICENSE](./LICENSE). Certificate designs, logos and issuer marks belong to their issuers, and this repository grants no rights to them.

This vault is personal and accepts no contributions. To report an error in the index, open a GitHub issue.

## Maintenance status

Active. The vault grows as courses complete, and the latest entry is dated 17 October 2026.
