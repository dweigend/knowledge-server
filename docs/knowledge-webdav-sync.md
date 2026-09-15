# Self-hosted Zotero file storage and annotation intake

Decision date: 2026-09-15. Status: binding target; implementation and migration
are pending. This decision records documentation research, not a verified
installation. No storage, account or synchronization settings changed as part
of this decision.

## Decision

Operate our own Zotero-compatible WebDAV file server. Use it for attachments in
the personal Zotero library on desktop, server and the official iPad app.
Retain Zotero.org for free library-data synchronization. Do not replace Zotero's
complete synchronization backend or require modified mobile clients.

This document owns file synchronization, mobile access and annotation intake.
The [Zotero ownership decision](knowledge-zotero-ownership.md) remains binding:
Zotero is the only literature manager and PDF authority. WebDAV is storage used
by Zotero, not a separately maintained document library. The
[source-view contract](knowledge-source-view.md) owns presentation and the
[extraction contract](knowledge-extraction.md) owns technical PDF derivations.

## Ownership and synchronization

| Content | Authority and transport |
| --- | --- |
| Literature metadata, collections and tags | Zotero; Zotero.org data sync |
| Reading notes and PDF annotations | Zotero; Zotero.org data sync |
| PDFs and other personal-library attachments | Zotero; our WebDAV file sync |
| Local attachment copies | Zotero-managed replicas for reading and processing |
| OCR, page maps and extraction quality issues | Immutable knowledge snapshots |
| Claims, assessments, cross-source Zettel and wiki | Knowledge database |
| Intake cursors and processing receipts | Technical application state |

Zotero documents data sync as free and unlimited. Self-hosting file storage
removes the Zotero attachment-storage quota for this personal-library workflow;
capacity still depends on disks, free space and backups. It does not make all
research data local-only. Metadata, notes and annotations still pass through
Zotero.org. The optional full-text sync setting can also upload extracted text
for search; choose and document that setting explicitly. See the official
[sync overview](https://www.zotero.org/support/sync) and
[sync preferences](https://www.zotero.org/support/preferences/sync).

Do not share or synchronize the live Zotero SQLite data directory through WebDAV,
a network drive or a generic folder-sync service. Use Zotero's supported stored
attachments and file-sync protocol. Local replicas and recovery backups are
permitted technical copies; they must never need independent literature edits.
Zotero warns against cloud-synced database directories in its
[alternative syncing guidance](https://www.zotero.org/support/sync#alternative_syncing_solutions).

## User workflow and limits

1. Add a paper to Zotero on a desktop or through a supported mobile import.
2. Let Zotero synchronize metadata and upload the attachment to WebDAV.
3. Open the attachment in the official Zotero iPad app.
4. Highlight passages, add typed comments, reading notes or ink annotations.
5. Let Zotero synchronize those objects back to the server's Zotero client.
6. Let the knowledge intake process detect changes and propose derived updates.

Use the same Zotero account and WebDAV configuration on every participating
client. Configure the server client to download attachments needed for knowledge
processing. A metadata record alone is not proof that its PDF has downloaded.
For offline iPad reading, download a collection's attachments before travel.
The iPad app supports annotation tools and collection downloads; see
[Zotero for iOS](https://www.zotero.org/support/ios),
[WebDAV setup](https://forums.zotero.org/discussion/112490/ios-with-webdav) and
[offline downloads](https://forums.zotero.org/discussion/94544/is-there-a-way-to-sync-all-attachments-on-ios).

The following constraints are accepted:

- Personal libraries can use WebDAV; Zotero group attachment sync cannot.
- Zotero.org's browser library cannot retrieve our WebDAV attachments. Use the
  native apps for reading and annotation. The knowledge web interface can resolve
  PDFs through its existing Zotero adapter, without adding another PDF store.
- Do not upload PDFs through Zotero.org's web library expecting them to appear
  automatically in WebDAV: that upload uses Zotero Storage.
- Linked files are not a substitute for stored attachments in the iPad workflow.
- Offline edits become available to the server only after the iPad synchronizes.

See the Zotero team's explanations of
[web-library access](https://forums.zotero.org/discussion/122943/zotero-web-library-with-webdav-sync),
[web uploads](https://forums.zotero.org/discussion/100949/copy-files-from-zotero-web-library-to-webdav)
and [stored attachments](https://forums.zotero.org/discussion/101227/webdav-file-sync-successfully-set-up-but-nothing-happens).

## Minimal deployment boundary

Use a maintained standard WebDAV implementation; do not implement WebDAV in our
Python application. Apache with `mod_dav` is a candidate, not a committed server
package. Inspect existing infrastructure before selecting the implementation.
A full cloud suite is not required solely to provide this endpoint.

Provide a dedicated storage directory, authentication and HTTPS with a trusted
certificate. Prefer private access through the existing VPN when compatible
with the iPad workflow. Tailscale HTTPS is a candidate; verify certificate,
hostname, device reachability and mobile access in the actual deployment.
Use Zotero's Verify Server operation on desktop and iPad as an initial check,
then test actual uploads and downloads. Do not infer compatibility from an
ordinary HTTP GET succeeding.

Keep credentials, runtime paths, attachment bytes and backups out of Git.
The WebDAV service must have access only to its own storage. Do not expose the
server client's local Zotero API: its reads are unauthenticated and it is
intended for applications on the same machine.

Record storage capacity and backup/restore procedures during implementation.
Synchronization is not a backup: deletions and bad edits can propagate.
Include the WebDAV store in the recovery plan alongside the Zotero library and
knowledge database. Existing backup commands must be inspected before claiming
that they cover this new store.

References: [Apache WebDAV](https://httpd.apache.org/docs/2.4/mod/mod_dav.html),
[Zotero HTTPS requirements](https://www.zotero.org/support/kb/webdav_and_https),
[Tailscale HTTPS](https://tailscale.com/docs/how-to/set-up-https-certificates) and
[Zotero Local API](https://www.zotero.org/support/dev/web_api/v3/local_api).

## Annotation intake

Zotero stores its own PDF annotations in its database rather than embedding
them into the PDF. A filesystem watcher on PDFs would miss these changes.
Read annotation and note objects through the API. The server's synchronized
Zotero client remains responsible for fetching library changes and attachments;
the knowledge application must not implement another Zotero sync engine.
See [annotation storage](https://www.zotero.org/support/kb/annotations_in_database).

Start with one scheduled Python intake operation against the existing local
Zotero adapter. A one-to-five-minute interval is an initial operational choice,
not a latency guarantee. No model is needed to detect changes or compare
versions. Use a single intake path for manual and scheduled execution.

The operation must:

1. Read changes since its last successfully processed local library version,
   including deletions. Verify supported endpoints on the installed client.
2. Resolve note/annotation parents to the correct literature item and attachment.
3. Record pending work and version receipts durably before advancing its cursor.
4. Coalesce changes for a source before invoking the existing knowledge workflow.
5. Resume interrupted work without duplicate proposals or lost updates.

Persist the minimum identity needed for provenance: API-instance identity,
library identity, Zotero object key, object version, parent attachment key and
source location. Current text is read from Zotero; preserve a bounded immutable
excerpt only when required to substantiate a derived record. Do not create a
second editable annotation or literature table.

Local API versions are specific to the Zotero instance and must not be compared
with Zotero.org API versions or versions from another client. Partition cursors
by instance and library. A changed instance identity requires an explicit
reconciliation before resuming; it must not silently rebind historical citations.
See [local object versions](https://www.zotero.org/support/dev/web_api/v3/local_api#object_versions)
and [incremental synchronization](https://www.zotero.org/support/dev/web_api/v3/syncing).

Later, if latency matters, Zotero's Streaming API can supply a library-change
notification over WebSockets. It does not deliver changed objects. Retrieve
changes through the same intake path, and keep reconnect/catch-up behavior.
Remote notifications do not prove that the local server client has synchronized.
Do not add streaming or a desktop plugin before polling proves insufficient.
See [Streaming API](https://www.zotero.org/support/dev/web_api/v3/streaming_api).

## Knowledge and citation rules

- Keep the quoted source passage separate from the reader's interpretation.
- Treat highlights as selected evidence candidates, not verified facts.
- Preserve links to the original annotation, its attachment and source location.
- Apply amendments as revisions; repeated processing must not create duplicates.
- Retain historical evidence when an annotation is changed or deleted; mark its
  live reference as changed/deleted and flag affected work for review.
- Preserve ink and image annotations as annotations. Handwriting recognition or
  visual interpretation is a separate optional step, not guaranteed plain text.
- Never transfer coordinates between original and cleaned PDF attachments
  without a verified page/position mapping. Pin the actual attachment and PDF
  identity used to derive evidence.
- Keep note editing in Zotero. Knowledge records contain cross-source work,
  references and necessary evidence snapshots, not competing reading notes.
- Use Hermes only for bounded derived proposals after changes are collected;
  ingestion and synchronization remain deterministic.

These rules extend existing provenance and revision contracts rather than
introducing another generic event framework or service layer.

## Why not a complete self-hosted Zotero backend?

Zotero's data server is open source, but Zotero describes private deployments as
technically challenging and unsupported. That is unnecessary for the accepted
storage goal. See [Zotero security and hosting](https://www.zotero.org/support/security)
and the [official data server](https://github.com/zotero/dataserver).

The independent Altero project was also researched. Its documentation describes
a self-hosted desktop sync service and web UI, but warns against using it as the
only home of an important library. It explicitly does not support the official
iOS/Android apps because they do not offer a runtime API-host setting. It is not
the selected architecture. See [Altero](https://github.com/eseifert/altero).

## Migration and acceptance

Preserve the existing account and object identities. Before changing settings,
inspect whether the current server pilot library is already synchronized with
the intended user library; do not assume that it is. Reconcile any separate
pilot objects explicitly to avoid duplicates and broken knowledge references.

Complete these steps in order:

1. Inventory stored versus linked attachments, missing files and active clients.
   Download available cloud files and recover unsynced files from the devices
   that contain them. Verify a complete backup before changing the backend.
2. Provision private WebDAV storage and HTTPS. Record credentials outside Git.
3. Configure the selected desktop and server clients for the same library and
   WebDAV endpoint. Let Zotero upload existing stored attachments.
4. Configure the iPad and test representative PDFs, including scanned and large
   documents. Compare attachment identities and bytes after synchronization.
5. Test highlighting, typed comments, reading-note edits and deletion on both
   desktop and iPad, including offline edits followed by reconnection.
6. Test intake restart/retry, duplicate suppression, amendments, deletions and
   historical citation preservation. Confirm there is no model call on reads.
7. Verify full attachment transfer and perform a recovery test. Only then remove
   obsolete cloud file copies using the appropriate storage-management action.
   Never delete literature or attachment items to free obsolete cloud storage.

Keep old copies until verified transfer. Do not routinely invoke destructive
sync reset options. The published
[file-sync troubleshooting guide](https://www.zotero.org/support/kb/files_not_syncing)
explains why matching metadata is not sufficient proof of file availability.

Acceptance requires all three clients to open the same PDFs, synchronized
annotations to reach the knowledge intake, stable historical citations and a
verified recovery path. Until these checks pass, report the target as pending;
documentation and configuration templates alone are not deployment evidence.
