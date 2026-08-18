PYTHON ?= python3

.PHONY: test extract validate enrich enrich-lmstudio probe-lmstudio validate-enrich merge-monthly validate-monthly build-chunks validate-chunks build-reports build-reports-lmstudio validate-reports import-notion-links validate-link-map pipeline pipeline-lmstudio probe-lmstudio-sh stage2-lmstudio-sh stage3-4-sh

test:
	$(PYTHON) -m pytest

extract:
	$(PYTHON) scripts/extract_raw.py --raw-root raw --store-root store

validate:
	$(PYTHON) scripts/validate_store.py --raw-root raw --store-root store

enrich:
	$(PYTHON) scripts/enrich_images.py --store-root store --provider mock

enrich-lmstudio:
	$(PYTHON) scripts/enrich_images.py --store-root store --provider lmstudio

probe-lmstudio:
	$(PYTHON) scripts/probe_lmstudio_vlm.py --image $(IMAGE)

validate-enrich:
	$(PYTHON) scripts/validate_enriched_images.py --store-root store

merge-monthly:
	$(PYTHON) scripts/merge_monthly.py --store-root store --monthly-root monthly

validate-monthly:
	$(PYTHON) scripts/validate_monthly.py --store-root store --monthly-root monthly

build-chunks:
	$(PYTHON) scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks

validate-chunks:
	$(PYTHON) scripts/validate_chunks.py --monthly-root monthly --chunks-root llm_chunks

build-reports:
	$(PYTHON) scripts/build_reports.py --chunks-root llm_chunks --reports-root reports --provider mock

build-reports-lmstudio:
	$(PYTHON) scripts/build_reports.py --chunks-root llm_chunks --reports-root reports --provider lmstudio

validate-reports:
	$(PYTHON) scripts/validate_reports.py --chunks-root llm_chunks --reports-root reports

import-notion-links:
	$(PYTHON) scripts/import_notion_links.py --input $(INPUT) --store-root store

validate-link-map:
	$(PYTHON) scripts/validate_link_map.py --store-root store

pipeline:
	$(PYTHON) scripts/run_pipeline.py --report-provider mock

pipeline-lmstudio:
	$(PYTHON) scripts/run_pipeline.py --enrich-provider lmstudio --report-provider lmstudio

probe-lmstudio-sh:
	IMAGE="$(IMAGE)" PYTHON="$(PYTHON)" scripts/00_probe_lmstudio_image.sh

stage2-lmstudio-sh:
	MONTH="$(MONTH)" PYTHON="$(PYTHON)" scripts/10_stage2_enrich_lmstudio.sh

stage3-4-sh:
	MONTH="$(MONTH)" PYTHON="$(PYTHON)" scripts/20_stage3_4_build_context.sh
