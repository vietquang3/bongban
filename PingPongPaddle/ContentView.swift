import SwiftUI
import CoreMotion
import Network
import UIKit

/// Đọc cảm biến chuyển động (100 Hz) và gửi UDP về máy tính.
/// Mỗi gói: "qx,qy,qz,qw,ax,ay,az"  (quaternion + gia tốc tuyến tính theo g)
/// Máy tính gửi lại "H" khi bóng chạm vợt -> điện thoại rung.
final class Sender: ObservableObject {
    @Published var running = false
    @Published var status = "Chưa chạy"
    @Published var sent = 0

    private let motion = CMMotionManager()
    private var conn: NWConnection?
    private let haptic = UIImpactFeedbackGenerator(style: .heavy)
    private var counter = 0

    func start(host: String, port: UInt16 = 5005) {
        guard motion.isDeviceMotionAvailable else {
            status = "Máy không có cảm biến chuyển động"
            return
        }
        guard let p = NWEndpoint.Port(rawValue: port) else { return }
        let c = NWConnection(host: NWEndpoint.Host(host), port: p, using: .udp)
        c.stateUpdateHandler = { [weak self] state in
            DispatchQueue.main.async {
                switch state {
                case .ready: self?.status = "Đang gửi tới \(host):\(port)"
                case .failed(let e): self?.status = "Lỗi: \(e.localizedDescription)"
                case .waiting(let e): self?.status = "Đang chờ mạng: \(e.localizedDescription)"
                default: break
                }
            }
        }
        c.start(queue: .global())
        conn = c
        running = true
        sent = 0
        counter = 0
        haptic.prepare()
        UIApplication.shared.isIdleTimerDisabled = true
        receiveLoop()

        motion.deviceMotionUpdateInterval = 1.0 / 100.0
        motion.startDeviceMotionUpdates(using: .xArbitraryZVertical, to: OperationQueue()) { [weak self] dm, _ in
            guard let self = self, let dm = dm else { return }
            let q = dm.attitude.quaternion
            let a = dm.userAcceleration
            let line = String(format: "%.5f,%.5f,%.5f,%.5f,%.4f,%.4f,%.4f",
                              q.x, q.y, q.z, q.w, a.x, a.y, a.z)
            self.conn?.send(content: line.data(using: .utf8), completion: .idempotent)
            self.counter += 1
            if self.counter % 50 == 0 {
                let n = self.counter
                DispatchQueue.main.async { self.sent = n }
            }
        }
    }

    private func receiveLoop() {
        conn?.receiveMessage { [weak self] data, _, _, error in
            guard let self = self else { return }
            if let d = data, let s = String(data: d, encoding: .utf8), s.hasPrefix("H") {
                DispatchQueue.main.async { self.haptic.impactOccurred() }
            }
            if error == nil && self.running { self.receiveLoop() }
        }
    }

    func stop() {
        running = false
        motion.stopDeviceMotionUpdates()
        conn?.cancel()
        conn = nil
        UIApplication.shared.isIdleTimerDisabled = false
        status = "Đã dừng"
    }
}

struct ContentView: View {
    @StateObject private var sender = Sender()
    @AppStorage("host") private var host = ""

    var body: some View {
        VStack(spacing: 24) {
            Text("🏓 Vợt bóng bàn")
                .font(.largeTitle).bold()

            VStack(alignment: .leading, spacing: 6) {
                Text("IP của máy tính (hiện trên màn hình game):")
                    .font(.footnote).foregroundColor(.gray)
                TextField("vd: 192.168.1.5", text: $host)
                    .keyboardType(.numbersAndPunctuation)
                    .disableAutocorrection(true)
                    .padding(12)
                    .background(Color(white: 0.15))
                    .cornerRadius(10)
                    .disabled(sender.running)
            }

            Button(action: {
                if sender.running { sender.stop() }
                else { sender.start(host: host.trimmingCharacters(in: .whitespaces)) }
            }) {
                Text(sender.running ? "DỪNG" : "BẮT ĐẦU")
                    .font(.title).bold()
                    .frame(maxWidth: .infinity, minHeight: 90)
                    .background(sender.running ? Color.red : Color.green)
                    .foregroundColor(.black)
                    .cornerRadius(16)
            }
            .disabled(host.isEmpty && !sender.running)

            Text(sender.status).foregroundColor(.gray)
            if sender.running {
                Text("Đã gửi: \(sender.sent) gói").foregroundColor(.gray)
                Text("Dán điện thoại lên vợt: ĐỈNH máy hướng về đầu vợt,\nmàn hình hướng ra phía mặt vợt.\nGiữ vợt tư thế sẵn sàng rồi nhấn SPACE trên máy tính.")
                    .font(.footnote).multilineTextAlignment(.center).foregroundColor(.gray)
            }
            Spacer()
        }
        .padding(24)
    }
}
