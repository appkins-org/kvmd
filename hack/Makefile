CHANGED_FILES = "$(shell git diff --name-only upstream/master...HEAD | grep -E '.*\.py$$')"

copy:
	mkdir -p .build
	for file in $(CHANGED_FILES); do \
		cp ../$$file .build/$$file; \
	done