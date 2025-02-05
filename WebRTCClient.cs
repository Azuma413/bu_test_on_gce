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
    public RTCConfiguration configuration;
}

[Serializable]
public class RTCIceServerJson
{
    public string[] urls;
}

public class WebRTCClient : MonoBehaviour
{
    [SerializeField] private RawImage displayImage;
    private RTCPeerConnection peerConnection;
    private MediaStream receiveStream;
    private RTCDataChannel dataChannel;
    [SerializeField] private string ServerUrl = "https://34.133.108.164:8443";
    [SerializeField] private int reconnectAttempts = 3;
    [SerializeField] private float reconnectDelay = 5f;
    private VideoStreamTrack videoStreamTrack;
    private bool isDisposed = false;
    private bool isReconnecting = false;
    private Coroutine reconnectCoroutine;

    private void Start()
    {
        ConnectWebRTC();
    }

    private void ConnectWebRTC()
    {
        if (!isReconnecting)
        {
            StartCoroutine(SetupWebRTC());
        }
    }

    private IEnumerator SetupWebRTC()
    {
        Debug.Log("Starting WebRTC setup...");
        
        // Configure and initialize RTCPeerConnection with ICE servers
        var config = GetDefaultConfiguration();
        peerConnection = new RTCPeerConnection(ref config);
        
        // Add transceiver to explicitly indicate we want to receive video
        RTCRtpTransceiverInit init = new RTCRtpTransceiverInit
        {
            direction = RTCRtpTransceiverDirection.RecvOnly
        };
        
        var transceiver = peerConnection.AddTransceiver(TrackKind.Video, init);
        Debug.Log("Added video transceiver with RecvOnly direction");

        // Note: Codec preferences are handled by default configuration
        Debug.Log("Using default video codec configuration");

        // Setup event handlers
        peerConnection.OnTrack = (RTCTrackEvent e) =>
        {
            Debug.Log($"OnTrack received: {e.Track.Kind}");
            if (e.Track is MediaStreamTrack track && track.Kind == TrackKind.Video)
            {
                Debug.Log("Received video track");
                receiveStream = new MediaStream();
                receiveStream.AddTrack(track);
                videoStreamTrack = track as VideoStreamTrack;
                videoStreamTrack.OnVideoReceived += UpdateDisplayImage;
            }
        };

        peerConnection.OnConnectionStateChange = state =>
        {
            Debug.Log($"Connection state changed to: {state}");
            if (state == RTCPeerConnectionState.Failed || state == RTCPeerConnectionState.Disconnected)
            {
                Debug.LogError($"Connection {state}");
                if (!isReconnecting)
                {
                    AttemptReconnect();
                }
            }
        };

        peerConnection.IceConnectionState.ToString();  // This line is just to suppress the warning

        peerConnection.OnIceCandidate = candidate =>
        {
            Debug.Log($"ICE candidate gathered: {candidate?.Candidate}");
        };

        peerConnection.OnIceGatheringStateChange = state =>
        {
            Debug.Log($"ICE gathering state changed to: {state}");
        };

        peerConnection.OnNegotiationNeeded = () =>
        {
            Debug.Log("Negotiation needed event triggered");
        };

        peerConnection.OnDataChannel = channel =>
        {
            Debug.Log("Data channel received");
            dataChannel = channel;
        };

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
        Debug.Log("Preparing offer to send to server...");
        Debug.Log($"Offer type: {desc.type}");
        Debug.Log($"Offer SDP: {desc.sdp}");

        var sdpType = desc.type.ToString().ToLower();
        Debug.Log($"Converted SDP type: {sdpType}");

        var config = GetDefaultConfiguration();
        var offerMessage = new WebRTCMessage
        {
            type = sdpType,
            sdp = desc.sdp,
            configuration = config
        };
        Debug.Log($"Using ICE Configuration: {JsonUtility.ToJson(config)}");

        string jsonOffer = JsonUtility.ToJson(offerMessage);
        Debug.Log($"Serialized JSON offer: {jsonOffer}");
        Debug.Log($"Sending offer to: {ServerUrl}/offer");
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
            string errorMessage = $"Failed to send offer: {request.error}\nResponse Code: {request.responseCode}";
            if (request.downloadHandler != null)
            {
                errorMessage += $"\nResponse: {request.downloadHandler.text}";
            }
            Debug.LogError(errorMessage);
            yield break;
        }

        WebRTCMessage response = null;
        RTCSessionDescription remoteDesc = default;

        try
        {
            Debug.Log("Received answer from server");
            Debug.Log($"Response: {request.downloadHandler.text}");
            
            response = JsonUtility.FromJson<WebRTCMessage>(request.downloadHandler.text);
            if (response == null)
            {
                throw new Exception("Failed to parse server response");
            }

            Debug.Log($"Answer SDP: {response.sdp}");
            remoteDesc = new RTCSessionDescription
            {
                type = RTCSdpType.Answer,
                sdp = response.sdp
            };
        }
        catch (Exception ex)
        {
            Debug.LogError($"Error processing server response: {ex.Message}");
            AttemptReconnect();
            yield break;
        }

        if (response != null)
        {
            Debug.Log("Setting remote description...");
            yield return StartCoroutine(SetRemoteDescriptionCoroutine(remoteDesc));
        }
        }
    }

    private void UpdateDisplayImage(Texture texture)
    {
        if (isDisposed) return;
        if (displayImage != null && texture != null)
        {
            Debug.Log($"Updating display image with texture: {texture.width}x{texture.height}");
            displayImage.texture = texture;
        }
        else if (displayImage == null)
        {
            Debug.LogError("Display image reference is missing");
        }
        else
        {
            Debug.LogError("Received null texture");
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

    private void CleanupResources(bool fullCleanup = true)
    {
        if (isDisposed && fullCleanup) return;
        
        if (fullCleanup)
        {
            isDisposed = true;
            if (reconnectCoroutine != null)
            {
                StopCoroutine(reconnectCoroutine);
                reconnectCoroutine = null;
            }
        }

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

    private IEnumerator SetRemoteDescriptionCoroutine(RTCSessionDescription remoteDesc)
    {
        var op = peerConnection.SetRemoteDescription(ref remoteDesc);
        yield return op;
        
        if (op.IsError)
        {
            throw new Exception($"Failed to set remote description: {op.Error.message}");
        }
        
        Debug.Log("Remote description set successfully");
        isReconnecting = false;
    }

    private void AttemptReconnect()
    {
        if (reconnectCoroutine != null)
        {
            StopCoroutine(reconnectCoroutine);
        }
        reconnectCoroutine = StartCoroutine(ReconnectCoroutine());
    }

    private IEnumerator ReconnectCoroutine()
    {
        isReconnecting = true;
        int attempts = 0;

        while (attempts < reconnectAttempts && !isDisposed)
        {
            Debug.Log($"Attempting to reconnect... Attempt {attempts + 1}/{reconnectAttempts}");
            CleanupResources(false);
            yield return new WaitForSeconds(reconnectDelay);
            ConnectWebRTC();
            attempts++;
        }

        if (attempts >= reconnectAttempts)
        {
            Debug.LogError("Max reconnection attempts reached");
            CleanupResources(true);
        }
    }

    private void OnDestroy()
    {
        CleanupResources(true);
    }

    private void OnApplicationQuit()
    {
        CleanupResources(true);
    }
}
