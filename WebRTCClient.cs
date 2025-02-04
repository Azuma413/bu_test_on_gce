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
    private const int MaxRetries = 3;
    private const float RetryDelay = 5f;
    private bool isDisposed = false;

    private void Start()
    {
        StartCoroutine(SetupWebRTCWithRetry());
    }

    private IEnumerator SetupWebRTCWithRetry()
    {
        int retryCount = 0;
        bool connected = false;

        while (!connected && retryCount < MaxRetries)
        {
            if (retryCount > 0)
            {
                Debug.Log($"Retrying WebRTC connection (Attempt {retryCount + 1}/{MaxRetries})");
                yield return new WaitForSeconds(RetryDelay);
            }

            bool setupResult = false;
            yield return StartCoroutine(SetupWebRTC((success) => setupResult = success));
            
            if (setupResult)
            {
                connected = true;
            }
            else
            {
                CleanupResources();
                retryCount++;
            }
        }

        if (!connected)
        {
            Debug.LogError("Failed to establish WebRTC connection after maximum retries");
        }
    }

    private IEnumerator SetupWebRTC(Action<bool> callback)
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
            Debug.Log($"Connection State Changed to: {state}");
            if (state == RTCPeerConnectionState.Failed)
            {
                Debug.LogError("Connection failed - ICE connectivity check failed");
            }
            else if (state == RTCPeerConnectionState.Disconnected)
            {
                Debug.LogWarning("Connection disconnected - ICE connection was interrupted");
            }
            else if (state == RTCPeerConnectionState.Connected)
            {
                Debug.Log("Connection established successfully - ICE connection is active");
            }
        };

        peerConnection.OnIceCandidate = candidate =>
        {
            Debug.Log($"ICE Candidate: {candidate.Candidate}, Type: {candidate.Type}, Protocol: {candidate.Protocol}");
        };

        peerConnection.OnDataChannel = channel =>
        {
            dataChannel = channel;
            Debug.Log("Data channel created");
        };

        // Create and send offer
        var op = peerConnection.CreateOffer();
        yield return op;

        if (op.IsError)
        {
            Debug.LogError($"Create Offer Error: {op.Error.message}");
            callback(false);
            yield break;
        }

        var desc = op.Desc;
        var opLocal = peerConnection.SetLocalDescription(ref desc);
        yield return opLocal;

        if (opLocal.IsError)
        {
            Debug.LogError($"Set Local Description Error: {opLocal.Error.message}");
            callback(false);
            yield break;
        }

        yield return StartCoroutine(SendOfferToServer(desc, callback));
    }

    private IEnumerator SendOfferToServer(RTCSessionDescription desc, Action<bool> callback)
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

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"Server Error: {request.error}");
                callback(false);
                yield break;
            }

            WebRTCMessage response;
            try
            {
                response = JsonUtility.FromJson<WebRTCMessage>(request.downloadHandler.text);
            }
            catch (Exception ex)
            {
                Debug.LogError($"Error parsing server response: {ex}");
                callback(false);
                yield break;
            }

            var type = RTCSdpType.Answer;
            var remoteDesc = new RTCSessionDescription
            {
                type = type,
                sdp = response.sdp
            };

            var opRemote = peerConnection.SetRemoteDescription(ref remoteDesc);
            yield return opRemote;

            if (opRemote.IsError)
            {
                Debug.LogError($"Set Remote Description Error: {opRemote.Error.message}");
                callback(false);
                yield break;
            }

            Debug.Log("WebRTC connection established successfully");
            callback(true);
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
        RTCConfiguration config = default;
        config.iceServers = new[]
        {
            new RTCIceServer { 
                urls = new[] { 
                    "stun:stun.l.google.com:19302",
                    "stun:stun1.l.google.com:19302",
                    "stun:stun2.l.google.com:19302",
                    "stun:stun3.l.google.com:19302",
                    "stun:stun4.l.google.com:19302"
                }
            },
            // Add TURN servers for better connectivity
            new RTCIceServer {
                urls = new[] { "turn:turn.webrtc.org:3478" },
                username = "webrtc",
                credential = "webrtc"
            }
        };
        config.iceTransportPolicy = RTCIceTransportPolicy.All;
        return config;
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
