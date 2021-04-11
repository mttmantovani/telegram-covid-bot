BOT	    := bot.py
PYTHON  := python
LOGFILE := bot.log

start:
	@nohup $(PYTHON) $(BOT) > $(LOGFILE) & 

restart:
	@PID=$$(ps aux | grep "$(PYTHON) $(BOT)" | awk '{print $$2}' | head -n1) \
	&& kill $$PID \
	&& echo "Killed $$PID" \
	&& nohup $(PYTHON) $(BOT) > $(LOGFILE) &

lint:
	@autoflake -iv --removed-all-unused-imports . && isort . && black .
