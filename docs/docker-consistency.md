# Docker consistency note

Docker images must run the same committed source code that local tests and CI validate.

Rules:

- Do not patch files under `src/` from `Dockerfile`.
- Put production logic in source files.
- Cover production behavior with tests.
- Keep Docker smoke-test commands aligned with `docker-compose.yml`, `.env.example`, and deployment docs.

Current Docker runtime state:

- `Dockerfile` copies committed source and installs the package.
- `config.yaml` is mounted read-only at `/app/config.yaml` by compose.
- `/app/data` is mounted for virtual position state.
- `/app/logs` is mounted for JSONL logs.
