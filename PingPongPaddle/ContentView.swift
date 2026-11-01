import SwiftUI
import UIKit

/// App chỉ làm một việc: biến màn hình điện thoại thành MỘT KHỐI MÀU HỒNG (magenta) sáng tối đa
/// để camera laptop dễ nhận diện vợt. Không dùng cảm biến, không cần WiFi.
/// Chạm 2 lần vào màn hình để thoát chế độ vợt.
struct ContentView: View {
    @State private var showing = false
    @State private var showHint = true
    @State private var savedBrightness: CGFloat = 0.5

    // Magenta thuần (OpenCV hue 150) – trùng màu mặc định trong game
    private let paddleColor = Color(red: 1.0, green: 0.0, blue: 1.0)

    var body: some View {
        ZStack {
            if showing {
                paddleScreen
            } else {
                homeScreen
            }
        }
        .statusBarHidden(showing)
    }

    private var homeScreen: some View {
        VStack(spacing: 24) {
            Spacer()
            Text("🏓 Vợt bóng bàn")
                .font(.largeTitle).bold()

            Button(action: enter) {
                Text("BẬT MÀN HÌNH VỢT")
                    .font(.title2).bold()
                    .frame(maxWidth: .infinity, minHeight: 90)
                    .background(Color.green)
                    .foregroundColor(.black)
                    .cornerRadius(16)
            }

            Text("Màn hình sẽ chuyển sang màu hồng sáng để camera laptop nhận ra vợt.\n\nDán điện thoại lên vợt: ĐỈNH máy hướng về đầu vợt, màn hình hồng quay về phía camera.\n\nChạm 2 lần vào màn hình để thoát.")
                .font(.footnote)
                .multilineTextAlignment(.center)
                .foregroundColor(.gray)
            Spacer()
        }
        .padding(24)
    }

    private var paddleScreen: some View {
        ZStack {
            paddleColor.ignoresSafeArea()
            if showHint {
                VStack {
                    Spacer()
                    Text("Chạm 2 lần để thoát")
                        .font(.footnote).bold()
                        .foregroundColor(.black)
                        .padding(.bottom, 40)
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture(count: 2, perform: leave)
    }

    private func enter() {
        savedBrightness = UIScreen.main.brightness
        UIScreen.main.brightness = 1.0                   // sáng tối đa
        UIApplication.shared.isIdleTimerDisabled = true  // không tự tắt màn hình
        showHint = true
        showing = true
        // Ẩn dòng chữ sau vài giây để khối hồng liền mạch, camera dễ bắt hơn
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { showHint = false }
    }

    private func leave() {
        UIScreen.main.brightness = savedBrightness
        UIApplication.shared.isIdleTimerDisabled = false
        showing = false
    }
}
