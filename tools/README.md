# Tools

## Seeding Firestore Emulator with dummy data

Prerequisites:
- Firestore emulator installed and runnable.

Steps:
1) Start Firestore emulator (dev project):  
   `firebase emulators:start --only firestore --project gsm-dev-f70d0 --config ./firebase.json` or `make emu-firestore`
2) In another terminal, run:  
   `make seed-emu`
3) Open the emulator UI and verify collections: `users`, `leagues`, `matches`, and `journalEntries` subcollections under users.

Notes:
- The seed script is designed **only** for the emulator.
- It checks `FIRESTORE_EMULATOR_HOST` and refuses to run unless it points to localhost.***
