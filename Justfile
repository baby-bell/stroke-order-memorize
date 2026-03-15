run:
	uv run uvicorn main:app --reload

test:
	uv run pytest
