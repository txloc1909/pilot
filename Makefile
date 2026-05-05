.PHONY: test

# Run all TypeScript/JS test files inside .pi/extensions using Node's built-in test runner
test-js:
	find .pi/extensions -type f \( -name '*.test.ts' -o -name '*.test.js' -o -name '*.spec.ts' -o -name '*.spec.js' \) -exec node --experimental-strip-types --test {} +

# Lint 
lint: 
	uv run ruff check src/

# Type checking
type-check:
	uv run mypy src/
