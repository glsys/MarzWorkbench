.PHONY: patch test

# Apply ordered, version-guarded git format-patches from ~/downloads.
patch:
	@set -eu; \
	patch_dir="$(HOME)/downloads"; \
	if [ ! -d "$$patch_dir" ]; then \
		echo "No numbered patches in $$patch_dir"; \
		exit 0; \
	fi; \
	patches="$$(find "$$patch_dir" -maxdepth 1 -type f -name '[0-9][0-9][0-9][0-9]-*.patch' -print | LC_ALL=C sort)"; \
	if [ -z "$$patches" ]; then \
		echo "No numbered patches in $$patch_dir"; \
		exit 0; \
	fi; \
	printf '%s\n' "$$patches" | while IFS= read -r file; do \
		name="$${file##*/}"; \
		file_seq="$${name%%-*}"; \
		file_version="$$(printf '%s\n' "$$name" | sed -nE 's/^[0-9]{4}-([0-9]+\.[0-9]+\.[0-9]+)-.+\.patch$$/\1/p')"; \
		if [ -z "$$file_version" ]; then \
			echo "Invalid patch filename: $$name" >&2; exit 2; \
		fi; \
		current_version="$$(cat version.txt 2>/dev/null || true)"; \
		current_seq="$$(cat .patch-sequence 2>/dev/null || true)"; \
		if ! printf '%s\n' "$$current_version" | grep -Eq '^V [0-9]+\.[0-9]+\.[0-9]+$$' || \
		   ! printf '%s\n' "$$current_seq" | grep -Eq '^[0-9]+$$'; then \
			echo "Invalid or missing version.txt / .patch-sequence" >&2; exit 2; \
		fi; \
		next_seq="$$((current_seq + 1))"; \
		if [ "$$file_seq" != "$$(printf '%04d' "$$next_seq")" ]; then \
			echo "Patch sequence mismatch for $$name: expected $$(printf '%04d' "$$next_seq")" >&2; exit 2; \
		fi; \
		version_edits="$$(awk '/^diff --git a\/version\.txt b\/version\.txt$$/{f=1;next} /^diff --git /{f=0} f && /^[+-]V [0-9]+\.[0-9]+\.[0-9]+$$/{print}' "$$file")"; \
		seq_edits="$$(awk '/^diff --git a\/\.patch-sequence b\/\.patch-sequence$$/{f=1;next} /^diff --git /{f=0} f && /^[+-][0-9]+$$/{print}' "$$file")"; \
		old_version="$$(printf '%s\n' "$$version_edits" | sed -n 's/^-V /V /p')"; \
		new_version="$$(printf '%s\n' "$$version_edits" | sed -n 's/^+V /V /p')"; \
		old_seq="$$(printf '%s\n' "$$seq_edits" | sed -n 's/^-//p')"; \
		new_seq="$$(printf '%s\n' "$$seq_edits" | sed -n 's/^+//p')"; \
		subject_version="$$(sed -nE 's/^Subject: \[PATCH\] ([0-9]+\.[0-9]+\.[0-9]+) .*/\1/p' "$$file" | head -n 1)"; \
		if [ "$$old_version" != "$$current_version" ] || \
		   [ "$$new_version" != "V $$file_version" ] || \
		   [ "$$old_seq" != "$$current_seq" ] || \
		   [ "$$new_seq" != "$$next_seq" ] || \
		   [ "$$subject_version" != "$$file_version" ]; then \
			echo "Patch metadata mismatch for $$name" >&2; exit 2; \
		fi; \
		release="$$(awk -v old="$${current_version#V }" -v new="$$file_version" 'BEGIN { \
			split(old,a,"."); split(new,b,"."); \
			if (b[1]==a[1] && b[2]==a[2] && b[3]==a[3]+1) print "patch"; \
			else if (b[1]==a[1] && b[2]==a[2]+1 && b[3]==0) print "minor"; \
			else if (b[1]==a[1]+1 && b[2]==0 && b[3]==0) print "major"; \
			else print "invalid"; \
		}')"; \
		if [ "$$release" = invalid ]; then \
			echo "Invalid SemVer transition for $$name: $$current_version -> $$new_version" >&2; exit 2; \
		fi; \
		tag=""; \
		if [ "$$release" != patch ]; then \
			tag="v$$file_version"; \
			if git show-ref --verify --quiet "refs/tags/$$tag"; then \
				echo "Tag already exists: $$tag" >&2; exit 2; \
			fi; \
		fi; \
		echo "Applying $$name ($$current_version -> $$new_version)"; \
		if ! git am "$$file"; then \
			git am --abort || true; \
			echo "Failed to apply $$name; patch retained" >&2; exit 1; \
		fi; \
		if [ "$$(cat version.txt)" != "$$new_version" ] || \
		   [ "$$(cat .patch-sequence)" != "$$next_seq" ]; then \
			echo "Applied patch has unexpected version or sequence: $$name (file retained)" >&2; exit 2; \
		fi; \
		if [ -n "$$tag" ]; then git tag "$$tag"; fi; \
		rm -- "$$file"; \
	done

# Launch the user's neck test document with complete terminal and FreeCAD logs.
test:
	FreeCAD /home/glsys/Nextcloud/guitar/marztest.FCStd --log-file /tmp/freecad.log 2>&1 | tee /tmp/freecad-terminal.log
