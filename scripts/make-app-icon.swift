// Draws the app icon: the sidebar's orbit mark (a ring with a tilted orbit, app/ui/desk.css .orbit) on a rounded
// accent-green tile, at 1024x1024 inside Apple's icon grid (an 824px tile with a 100px margin).
// Usage: swift scripts/make-app-icon.swift <out.png>; scripts/make-app-icon.sh turns it into app/macos/AppIcon.icns.
import AppKit

let size = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon-1024.png"
guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
                                 samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                 bytesPerRow: 0, bitsPerPixel: 0) else { fatalError("No bitmap") }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let rgb = { (hex: Int, alpha: CGFloat) in
    NSColor(srgbRed: CGFloat((hex >> 16) & 255) / 255, green: CGFloat((hex >> 8) & 255) / 255,
            blue: CGFloat(hex & 255) / 255, alpha: alpha)
}

// The tile: the app's accent green (--accent #1f5c4a), a little lighter at the top, with a soft shadow below.
let tile = NSRect(x: 100, y: 100, width: 824, height: 824)
let shape = NSBezierPath(roundedRect: tile, xRadius: 185, yRadius: 185)
NSGraphicsContext.saveGraphicsState()
let shadow = NSShadow()
shadow.shadowColor = rgb(0x000000, 0.28)
shadow.shadowOffset = NSSize(width: 0, height: -10)
shadow.shadowBlurRadius = 24
shadow.set()
rgb(0x1f5c4a, 1).setFill()
shape.fill()
NSGraphicsContext.restoreGraphicsState()
NSGradient(starting: rgb(0x2b7a62, 1), ending: rgb(0x1a4d3e, 1))!.draw(in: shape, angle: -90)

// The mark, centred: a ring of diameter D and an ellipse 1.625D by 0.625D turned 30 degrees, its line half the ring's,
// in the same proportions as .orbit and .orbit:after.
let centre = NSPoint(x: 512, y: 512)
let d: CGFloat = 430
let ring = NSBezierPath(ovalIn: NSRect(x: centre.x - d / 2, y: centre.y - d / 2, width: d, height: d))
ring.lineWidth = 44
rgb(0xf3f5f2, 1).setStroke()
ring.stroke()

let orbit = NSBezierPath(ovalIn: NSRect(x: -d * 1.625 / 2, y: -d * 0.625 / 2, width: d * 1.625, height: d * 0.625))
orbit.lineWidth = 22
var turn = AffineTransform(translationByX: centre.x, byY: centre.y)
turn.rotate(byDegrees: 30)
orbit.transform(using: turn)
rgb(0x82c4aa, 1).setStroke()
orbit.stroke()

NSGraphicsContext.restoreGraphicsState()
guard let png = rep.representation(using: .png, properties: [:]) else { fatalError("No PNG") }
try png.write(to: URL(fileURLWithPath: out))
print(out)
