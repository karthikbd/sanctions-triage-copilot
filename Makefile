.PHONY: install test evals evals-llm serve mcp docker
install:   ; pip install -e ".[mcp,dev]"
test:      ; pytest -q
evals:     ; python evals/run_evals.py
evals-llm: ; python evals/run_evals.py --adjudicator claude
serve:     ; stc serve
mcp:       ; stc mcp
docker:    ; docker compose up --build
