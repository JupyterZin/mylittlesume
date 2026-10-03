# Talos — atalhos. No servidor, rode como o usuário administrador (não como talos).
CORE := core
UV := uv --directory $(CORE)
PROD := /opt/talos

.PHONY: dev test lint e2e doctor backup restore deploy migrate

dev:            ## arranca o core localmente (usa variáveis do ambiente atual)
	$(UV) run talos run

test:           ## suíte offline (fakes; não consome a assinatura)
	$(UV) run pytest -q

lint:
	$(UV) run ruff check talos tests

e2e:            ## caso âncora REAL (consome a assinatura) — só sob demanda
	$(UV) run pytest -q -m e2e -o addopts=''

doctor:
	sudo -u talos --preserve-env=PATH bash -c 'set -a; . /etc/talos/secrets.env; set +a; $(PROD)/core/.venv/bin/talos doctor'

backup:
	sudo -u talos $(PROD)/infra/scripts/backup.sh

restore:        ## make restore FILE=/var/lib/talos/backups/talos-AAAAMMDD-HHMM.tar.gz
	sudo $(PROD)/infra/scripts/restore.sh $(FILE)

deploy:         ## sincroniza o repo para /opt/talos, instala deps, migra e reinicia
	sudo infra/scripts/deploy.sh

migrate:
	sudo -u talos bash -c 'set -a; . /etc/talos/secrets.env; set +a; $(PROD)/core/.venv/bin/talos migrate'
