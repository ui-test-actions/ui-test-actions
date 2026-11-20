import UIKit

@main
class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        let appWindow = UIWindow(frame: UIScreen.main.bounds)
        appWindow.rootViewController = Fixture()
        appWindow.makeKeyAndVisible()
        window = appWindow
        return true
    }
}

final class Fixture: UIViewController {
    private let status = UILabel()
    private let field = UITextField()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 25/255, green: 43/255, blue: 66/255, alpha: 1)
        status.text = "BEFORE · Ready for input"
        status.textColor = .white
        status.font = .boldSystemFont(ofSize: 22)
        status.textAlignment = .center
        status.adjustsFontSizeToFitWidth = true

        field.placeholder = "Enter test text"
        field.borderStyle = .roundedRect
        field.backgroundColor = .white
        field.autocorrectionType = .no
        field.autocapitalizationType = .none

        let apply = UIButton(type: .system)
        apply.setTitle("Apply change", for: .normal)
        apply.backgroundColor = .white
        apply.layer.cornerRadius = 8
        apply.addTarget(self, action: #selector(applyChange), for: .touchUpInside)

        let rows = UIStackView(arrangedSubviews: (1...30).map { number in
            let row = UILabel()
            row.text = "Swipe row \(number)"
            row.textColor = .white
            row.font = .systemFont(ofSize: 20)
            return row
        })
        rows.axis = .vertical
        rows.spacing = 26
        rows.translatesAutoresizingMaskIntoConstraints = false
        let scroll = UIScrollView()
        scroll.keyboardDismissMode = .onDrag
        scroll.addSubview(rows)

        let stack = UIStackView(arrangedSubviews: [status, field, apply, scroll])
        stack.axis = .vertical
        stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        let safe = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: safe.topAnchor, constant: 24),
            stack.leadingAnchor.constraint(equalTo: safe.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: safe.trailingAnchor, constant: -24),
            stack.bottomAnchor.constraint(equalTo: safe.bottomAnchor, constant: -16),
            rows.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 12),
            rows.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor),
            rows.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor),
            rows.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor),
            rows.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor),
            field.heightAnchor.constraint(equalToConstant: 42),
            apply.heightAnchor.constraint(equalToConstant: 45),
        ])
    }

    @objc private func applyChange() {
        let text = field.text ?? ""
        status.text = "AFTER · " + (text.isEmpty ? "Button tapped" : text)
        view.backgroundColor = UIColor(red: 23/255, green: 99/255, blue: 59/255, alpha: 1)
        view.endEditing(true)
    }
}
