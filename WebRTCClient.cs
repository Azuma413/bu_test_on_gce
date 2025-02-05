using UnityEngine;
using Unity.WebRTC;
using System.Collections;
using UnityEngine.UI;
using System;
using System.Text;
using UnityEngine.Networking;

public class BypassCertificate : CertificateHandler
{
    protected override bool ValidateCertificate(byte[] certificateData)
    {
        return true;
    }
}

[Serializable]
public class WebRTCMessage
{
    public string type;
    public string sdp;
}

public class WebRTCClient : MonoBehaviour
{
    [SerializeField] private RawImage displayImage;
    private RTCPeerConnection peerConnection;
    private MediaStream receiveStream;
    private RTCDataChannel dataChannel;
    [SerializeField] private string ServerUrl = "https://34.133.108.164:8443";
    private VideoStreamTrack videoStreamTrack;
    private bool isDisposed = false;

    private void Start()
    {
        StartCoroutine(SetupWebRTC());
    }

    private IEnumerator SetupWebRTC()
    {
        // Configure and initialize RTCPeerConnection with ICE servers
        var config = GetDefaultConfiguration();
        peerConnection = new RTCPeerConnection(ref config);

        // Setup event handlers
        peerConnection.OnTrack = (RTCTrackEvent e) =>
        {
            if (e.Track is MediaStreamTrack track && track.Kind == TrackKind.Video)
            {
                receiveStream = new MediaStream();
                receiveStream.AddTrack(track);
                videoStreamTrack = track as VideoStreamTrack;
                videoStreamTrack.OnVideoReceived += UpdateDisplayImage;
            }
        };

        peerConnection.OnConnectionStateChange = state =>
        {
            if (state == RTCPeerConnectionState.Failed)
            {
                Debug.LogError("Connection failed");
                CleanupResources();
            }
        };

        peerConnection.OnDataChannel = channel => dataChannel = channel;

        // Create and send offer
        var op = peerConnection.CreateOffer();
        yield return op;

        var desc = op.Desc;
        var opLocal = peerConnection.SetLocalDescription(ref desc);
        yield return opLocal;

        yield return StartCoroutine(SendOfferToServer(desc));
    }

    private IEnumerator SendOfferToServer(RTCSessionDescription desc)
    {
        var offerMessage = new WebRTCMessage
        {
            type = desc.type.ToString().ToLower(),
            sdp = desc.sdp
        };

        string jsonOffer = JsonUtility.ToJson(offerMessage);
        using (var request = new UnityWebRequest(ServerUrl + "/offer", "POST"))
        {
            byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonOffer);
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.certificateHandler = new BypassCertificate();
            request.timeout = 60; // Increase timeout to 60 seconds

            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                WebRTCMessage response = JsonUtility.FromJson<WebRTCMessage>(request.downloadHandler.text);

                var type = RTCSdpType.Answer;
                var remoteDesc = new RTCSessionDescription
                {
                    type = type,
                    sdp = response.sdp
                };

                yield return peerConnection.SetRemoteDescription(ref remoteDesc);
            }
        }
    }

    private void UpdateDisplayImage(Texture texture)
    {
        if (isDisposed) return;
        if (displayImage != null && texture != null)
        {
            displayImage.texture = texture;
        }
        else if (displayImage == null)
        {
            Debug.LogError("Display image reference is missing");
        }
    }

    private RTCConfiguration GetDefaultConfiguration()
    {
        return new RTCConfiguration
        {
            iceServers = new[] {
                new RTCIceServer { 
                    urls = new[] { "stun:stun.l.google.com:19302" }
                }
            }
        };
    }

    private void CleanupResources()
    {
        if (isDisposed) return;
        isDisposed = true;

        if (videoStreamTrack != null)
        {
            videoStreamTrack.OnVideoReceived -= UpdateDisplayImage;
            videoStreamTrack.Dispose();
            videoStreamTrack = null;
        }

        if (peerConnection != null)
        {
            peerConnection.Close();
            peerConnection.Dispose();
            peerConnection = null;
        }

        if (receiveStream != null)
        {
            receiveStream.Dispose();
            receiveStream = null;
        }

        if (dataChannel != null)
        {
            dataChannel.Close();
            dataChannel = null;
        }
    }

    private void OnDestroy()
    {
        CleanupResources();
    }

    private void OnApplicationQuit()
    {
        CleanupResources();
    }
}
