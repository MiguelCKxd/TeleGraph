import Foundation
import CoreGraphics

// CSS rectangles use the layout viewport. UIKit uses points in this WKWebView,
// which may be a split window and need not match the process's main screen.
struct TGNativeViewportGeometry {
    let visibleCSS: CGRect
    let bounds: CGRect
    let scale: Double

    init?(_ data: [String: Any], bounds: CGRect) {
        guard let width = data["width"] as? Double, let height = data["height"] as? Double,
              let left = data["offsetLeft"] as? Double, let top = data["offsetTop"] as? Double,
              [width, height, left, top].allSatisfy({ $0.isFinite }), width > 0, height > 0,
              bounds.width > 0, bounds.height > 0 else { return nil }
        let scale = bounds.width / width
        guard scale.isFinite, (0.125...8).contains(scale) else { return nil }
        self.visibleCSS = CGRect(x: left, y: top, width: width, height: height)
        self.bounds = bounds
        self.scale = scale
    }

    func rect(x: Double, y: Double, width: Double, height: Double) -> CGRect? {
        guard [x, y, width, height].allSatisfy({ $0.isFinite }), width >= 28, height >= 28 else { return nil }
        let css = CGRect(x: x, y: y, width: width, height: height)
        guard visibleCSS.insetBy(dx: -0.5, dy: -0.5).contains(css) else { return nil }
        let native = CGRect(x: (x - visibleCSS.minX) * scale, y: (y - visibleCSS.minY) * scale,
                            width: width * scale, height: height * scale)
        return bounds.insetBy(dx: -1, dy: -1).contains(native) ? native : nil
    }
}
