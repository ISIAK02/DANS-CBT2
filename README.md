# DANS CBT

DANS CBT is a no-Node CBT platform: the browser is plain HTML/CSS/ES modules, privileged APIs are Python Vercel Functions, Firebase Authentication and Firestore are the source of truth, Cloudinary stores payment receipts and uploaded PDFs, and PDF extraction/question generation runs in Python.

The dashboard includes a local study coach that uses a student's own exam history to calculate recent performance, missed-question signals, and a recommended next practice session. It uses deterministic Python logic and Firestore data only; it does not call or bill an AI API.

## Vercel deployment

1. Create a Vercel project connected to this repository. No build command is required. `pyproject.toml` explicitly points Vercel to `api/index.py`, which routes the Python API endpoints while the root remains static.
2. In Firebase Authentication, enable Email/Password. Create Firestore in production mode and deploy `firestore.rules`. Create the first user, then set that user's `users/{uid}.role` to `admin` in the Firebase console.
3. Create Cloudinary folders for receipts and PDFs. Authenticated Cloudinary delivery is recommended for production; the Python function signs upload and download requests, and the browser never receives the Cloudinary secret.
4. Add the variables from `.env.example` in Vercel Project Settings > Environment Variables for Production, Preview, and Development as needed. Redeploy after changing them.

`FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_STORAGE_BUCKET`, `FIREBASE_MESSAGING_SENDER_ID`, and `FIREBASE_APP_ID` are public Firebase web configuration values and are returned by `/api/config`. `FIREBASE_PRIVATE_KEY`, `FIREBASE_CLIENT_EMAIL`, and all Cloudinary credentials are private server variables and must never be put in frontend files. The private key may contain escaped `\\n`; the API converts those to real newlines.

## Local development

Serve the project directory with any static-file server and provide the same environment variables to the Vercel Functions runtime. Install the packages in `requirements.txt` in a Python 3.11 environment. OCR is optional at runtime because the engine first extracts native PDF text; scanned PDFs require a Tesseract binary available in the selected Python deployment environment.

## Security model

Client requests carry Firebase ID tokens. Every privileged function verifies the token and, for admin operations, reads the role from `users/{uid}`. Firestore rules deny direct writes to protected collections. Payment approval creates `approved_pending_activation`; only a transactional activation request can set server timestamps and start the subscription. Active subscription checks run before document processing and exam operations.

## Limitations to plan before high-volume production

Vercel Python functions have request-size and execution-time limits. PDF bytes are uploaded directly to authenticated Cloudinary storage and the Python function receives only a signed reference, avoiding the serverless request-body limit. Processing still depends on the function's memory and execution-time limits. For image-only PDFs, add a deployment with a Tesseract binary and wire OCR into `api/pdf_engine.py`; native text PDFs are handled without a paid AI API.