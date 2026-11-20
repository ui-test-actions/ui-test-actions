# Thought Meadow with native iOS accessibility

The external Python agent selected the visible `New note` button and focused the SwiftUI title and body through current AXe element references. It entered the Unicode title and three-line body. The AX tree returned the exact content from the `AXTextField` and `AXTextArea`. The agent opened the Markdown preview. After the live session had ended, a separate job step asserted the exact title and body in one active, non-sample note in the application's persistent vault.

The workflow used the AXe scroll follow-up action pin `032f3405eb0ee69f59957594a52b4b632d7778e9` and AXe 2.1.1. It checked a live application tree and a valid simulator screenshot before starting the action. The earlier run at this action pin had timed out during initial screenshot capture. [Successful run 44700277428](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44700277428) · [Earlier timeout](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44695318721) · [Pinned upstream app](../../../real-apps/apps.json)

[Before](before.png) · [After](after.png) · [Preview](preview.png) · [Exact AX fields](external.json) · [Independent vault assertion](result.json)
