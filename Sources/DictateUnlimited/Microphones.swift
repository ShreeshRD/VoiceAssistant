import AppKit
import AVFoundation
import CoreAudio

struct MicrophoneDevice: Identifiable, Equatable {
    let id: String
    let deviceID: AudioDeviceID
    let name: String
}
@MainActor final class MicrophoneController: ObservableObject {
    @Published private(set) var devices: [MicrophoneDevice] = []
    @Published var selectedUID = UserDefaults.standard.string(forKey:"microphoneUID") ?? "" {
        didSet { UserDefaults.standard.set(selectedUID,forKey:"microphoneUID"); refresh() }
    }
    @Published private(set) var inputName = "No input available"
    @Published private(set) var permission = "Not requested"
    @Published private(set) var accessibilityGranted = false
    init() { refresh() }
    private static func string(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
        var a=AudioObjectPropertyAddress(mSelector:selector,mScope:kAudioObjectPropertyScopeGlobal,mElement:kAudioObjectPropertyElementMain)
        var value: Unmanaged<CFString>?; var size=UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        guard AudioObjectGetPropertyData(id,&a,0,nil,&size,&value)==noErr else { return nil }
        return value?.takeRetainedValue() as String?
    }
    private static func defaultInput() -> AudioDeviceID? {
        var a=AudioObjectPropertyAddress(mSelector:kAudioHardwarePropertyDefaultInputDevice,mScope:kAudioObjectPropertyScopeGlobal,mElement:kAudioObjectPropertyElementMain)
        var id=AudioDeviceID(0);var size=UInt32(MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),&a,0,nil,&size,&id)==noErr,id != 0 else { return nil };return id
    }
    func refresh() {
        var a=AudioObjectPropertyAddress(mSelector:kAudioHardwarePropertyDevices,mScope:kAudioObjectPropertyScopeGlobal,mElement:kAudioObjectPropertyElementMain)
        var size:UInt32=0
        if AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject),&a,0,nil,&size)==noErr, size > 0 {
            var ids=[AudioDeviceID](repeating:0,count:Int(size)/MemoryLayout<AudioDeviceID>.size)
            let status=ids.withUnsafeMutableBytes { AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),&a,0,nil,&size,$0.baseAddress!) }
            if status==noErr {
                devices=ids.compactMap { id in
                    var input=AudioObjectPropertyAddress(mSelector:kAudioDevicePropertyStreams,mScope:kAudioDevicePropertyScopeInput,mElement:kAudioObjectPropertyElementMain)
                    var count:UInt32=0
                    guard AudioObjectGetPropertyDataSize(id,&input,0,nil,&count)==noErr,count>0,
                          let uid=Self.string(id,kAudioDevicePropertyDeviceUID) else { return nil }
                    return MicrophoneDevice(id:uid,deviceID:id,name:Self.string(id,kAudioObjectPropertyName) ?? "Microphone")
                }.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
            }
        }
        if selectedUID.isEmpty { inputName=devices.first { $0.deviceID==Self.defaultInput() }?.name ?? "No system input available" }
        else { inputName=devices.first { $0.id==selectedUID }?.name ?? "Selected microphone disconnected" }
        switch AVCaptureDevice.authorizationStatus(for:.audio) {
        case .authorized: permission="Allowed"
        case .denied: permission="Denied — enable Microphone in System Settings"
        case .restricted: permission="Restricted by macOS"
        default: permission="Not requested — choose Test microphone"
        }
        accessibilityGranted=TextInsertion.trusted
    }
    func selectedDeviceID() throws -> AudioDeviceID? {
        refresh()
        if selectedUID.isEmpty {
            guard let id=Self.defaultInput(),devices.contains(where:{$0.deviceID==id}) else { throw AppError("No microphone is available. Connect an input and choose Refresh.") }
            return id
        }
        guard let device=devices.first(where:{$0.id==selectedUID}) else { throw AppError("Selected microphone is disconnected. Choose an available input or System default.") }
        return device.deviceID
    }
}
