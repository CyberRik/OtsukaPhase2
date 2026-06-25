"""Document generation — the chatbot's 'do stuff' surface.

Four chat tools generate real files (saved under config.GENERATED_DIR, gitignored):
  generate_proposal  — 4-slide PPTX sales proposal, grounded in a deal's SPR data
  generate_ringisho  — formal 稟議書 DOCX (customer IT-manager -> CEO), grounded
  generate_pptx      — general-purpose PPTX from a prompt (LLM-authored)
  generate_docx      — general-purpose DOCX from a prompt (LLM-authored)

Layering:
  render.py     pure, LLM-free pptx/docx rendering from a normalized spec
  context.py    deterministic deal context (store + scoring), for the grounded pair
  narrative.py  grounded persuasive prose (LLM if available, templated fallback)
  proposal.py   deal context  -> deck spec -> render_pptx
  ringisho.py   deal context  -> doc spec  -> render_docx
  author.py     free prompt    -> spec (LLM only), for the general pair
  registry.py   doc_id -> file, so the bridge can serve generated files for download
"""
