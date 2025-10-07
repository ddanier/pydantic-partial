default:
    just --list

[unix]
_install-pre-commit:
    #!/usr/bin/env bash
    if ( which pre-commit > /dev/null 2>&1 )
    then
        pre-commit install --install-hooks
    else
        echo "-----------------------------------------------------------------"
        echo "pre-commit is not installed - cannot enable pre-commit hooks!"
        echo "Recommendation: Install pre-commit ('brew install pre-commit')."
        echo "-----------------------------------------------------------------"
    fi

[windows]
_install-pre-commit:
    #!powershell.exe
    Write-Host "Please ensure pre-commit hooks are installed using 'pre-commit install --install-hooks'"

install: (uv "sync" "--group" "dev") && _install-pre-commit

update: (uv "sync" "--group" "dev")

uv *args:
    uv {{args}}

test *args: (uv "run" "pytest" "--cov=pydantic_partial" "--cov-report" "term-missing:skip-covered" args)

test-all: (uv "run" "tox")

ruff *args: (uv "run" "ruff" "check" "pydantic_partial" "tests" args)

pyright *args: (uv "run" "pyright" "pydantic_partial" args)

lint: ruff pyright

release version: (uv "version" version)
    git add pyproject.toml
    git commit -m "release: 🔖 v$(uv version --short)" --no-verify
    git tag "v$(uv version --short)"
    git push
    git push --tags

version-bump version_bump: (uv "version" "--bump" version_bump)
    git add pyproject.toml
    git commit -m "release: 🔖 v$(uv version --short)" --no-verify
    git tag "v$(uv version --short)"
    git push
    git push --tags
