# Re-resolve against the current hassette version
uv lock

# Commit the updated lockfile
git add uv.lock
git commit -m "update uv.lock for hassette upgrade"
