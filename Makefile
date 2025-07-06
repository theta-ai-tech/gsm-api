.PHONY: dev deploy

dev:
	@echo "Running local function on :5001"
	cd functions && source venv/bin/activate && \
		functions-framework --target health --port 5001

deploy:
	firebase deploy --only functions
