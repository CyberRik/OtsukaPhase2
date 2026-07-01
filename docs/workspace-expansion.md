# Workspace Expansion

## Overview

The `search_workspace_documents` capability has been expanded to search your entire local `E:\my_stuff` directory by default, instead of just the isolated `senpai/data/workspace` folder. 

This enables the chatbot to automatically discover, read, and cite your local documents (PDFs, DOCX, TXT, MD, XLSX, PPTX) no matter how deeply nested they are within your project structures.

## Performance Optimization (Pruning)

Because `E:\my_stuff` is a massive parent directory that contains heavy development folders, performing a standard recursive file search (`rglob("*")`) would freeze the backend server and consume excessive memory as it tried to walk through tens of thousands of temporary files.

To prevent this and keep the workspace search practically instantaneous, the `list_documents()` logic in `senpai/workspace/sandbox.py` has been rewritten to use an **optimized pruning directory walker** (`os.walk`).

### Ignored Directories

The walker intercepts the directory tree traversal and immediately **skips** any directories that match the following names (or start with a dot):

- `.git`
- `node_modules`
- `.venv`
- `venv`
- `.next`
- `__pycache__`
- `dist`

Because it prunes these directories *before* descending into them, it completely avoids enumerating the massive amounts of files inside them, keeping the scan localized only to your actual documents and source files.

## Usage

You don't need to do anything special to use this feature. Simply ask the chatbot to find information from your files:
> *"Search my local files for the latest Yamato quote."*

The chatbot will recursively scan `E:\my_stuff`, find the file (even if it's deeply hidden in a sub-project), execute parallel extraction tasks on the candidates, and return a cited response.
