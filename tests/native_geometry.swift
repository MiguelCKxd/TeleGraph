import Foundation
import CoreGraphics

@main struct NativeGeometryTests {
    static func main() {
        let full = CGRect(x: 0, y: 0, width: 390, height: 844)
        let viewport = TGNativeViewportGeometry(["width": 390.0, "height": 500.0, "offsetLeft": 0.0, "offsetTop": 170.0], bounds: full)!
        precondition(viewport.rect(x: 20, y: 190, width: 44, height: 44) == CGRect(x: 20, y: 20, width: 44, height: 44))
        precondition(viewport.rect(x: 20, y: 169, width: 44, height: 44) == nil)
        precondition(viewport.rect(x: 20, y: 650, width: 44, height: 44) == nil)
        // Real WebKit keyboard sample: pageTop=scrollY=396 despite offsetTop=396.
        // The JS bridge normalizes their difference to the client origin zero.
        let safari = TGNativeViewportGeometry(["width": 402.0, "height": 478.0, "offsetLeft": 0.0, "offsetTop": 0.0], bounds: CGRect(x: 0, y: 0, width: 402, height: 874))!
        precondition(safari.rect(x: 12, y: 334, width: 48, height: 54) == CGRect(x: 12, y: 334, width: 48, height: 54))
        let zoomed = TGNativeViewportGeometry(["width": 195.0, "height": 250.0, "offsetLeft": 10.0, "offsetTop": 100.0], bounds: full)!
        precondition(zoomed.rect(x: 30, y: 120, width: 44, height: 44) == CGRect(x: 40, y: 40, width: 88, height: 88))
        let split = TGNativeViewportGeometry(["width": 320.0, "height": 700.0, "offsetLeft": 0.0, "offsetTop": 0.0], bounds: CGRect(x: 0, y: 0, width: 320, height: 700))!
        precondition(split.rect(x: 276, y: 656, width: 44, height: 44) == CGRect(x: 276, y: 656, width: 44, height: 44))
        for invalid in [0.0, -1.0, Double.nan, Double.infinity] {
            precondition(TGNativeViewportGeometry(["width": invalid, "height": 844.0, "offsetLeft": 0.0, "offsetTop": 0.0], bounds: full) == nil)
            precondition(viewport.rect(x: invalid, y: 190, width: 44, height: 44) == nil || invalid == 0)
        }
        precondition(viewport.rect(x: 20, y: 190, width: 27, height: 44) == nil)
        print("Native geometry: keyboard offset, zoom, split window and invalid input OK")
    }
}
