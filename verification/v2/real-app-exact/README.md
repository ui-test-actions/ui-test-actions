# Upstream applications at the five-platform action pin

These runs load `ui-test-actions/ui-test-actions@b57a9501805d6b75f94c6fa7ac1df4e37726a959` from GitHub. The external client used the documented connection artifact and private token file. Its before and after screenshots show what changed in the live app. The runner independently checked the written document, persisted settings, or note vault once the live session had ended.

| Target | App and observed outcome | Run | Evidence |
| --- | --- | --- | --- |
| Windows | LocalSend changed to Arabic RTL and retained the mixed-direction receiver alias. | [44694463531](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44694463531) | [Screenshots and settings assertion](../flutter-windows/) |
| macOS | CotEditor replaced the document with a three-line Unicode sample and saved it. The client confirmed exact clipboard equality. | [44700501147](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44700501147) | [Screenshots and saved-content digest](macos/) |
| Linux | LocalSend changed to Arabic RTL and retained the mixed-direction receiver alias. | [44697310688](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44697310688) | [Screenshots and settings assertion](../flutter-linux/) |
| Android | Markor passed the visible Android storage permission prompt, opened the staged file, replaced the text, and saved it. | [44700501182](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44700501182) | [Screenshots and saved-content digest](android/) |
| iOS | Thought Meadow saved a new note, rendered its Markdown preview, and returned the note in an Arabic search. The runner matched the exact Unicode title and body in the saved vault. | [44700501405](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44700501405) | [Editor, preview, search, and vault assertion](ios/) |

[Exact upstream app revisions and hashes](../../real-apps/apps.json) · [Reproduction instructions](../../real-apps/README.md)
