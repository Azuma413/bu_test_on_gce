using UnityEngine;
using Unity.WebRTC;
using System.Collections;
using UnityEngine.UI;
using System;
using System.Text;
using UnityEngine.Networking;
using Newtonsoft.Json.Linq;

public class UnityWebRTCClient : MonoBehaviour
{
    [SerializeField] private RawImage displayImage;
    private RTCPeerConnection peerConnection;
    private MediaStream receiveStream;
    private RTCDataChannel dataChannel;
    [SerializeField] private string ServerUrl = "http://YOUR_GCE_IP:8080";
    private VideoStreamTrack videoStreamTrack;

    private void Start()
    {
        StartCoroutine(SetupWebRTC());
    }

    private IEnumerator SetupWebRTC()
    {
        // Initialize WebRTC
        WebRTC.Initialize();

        // Configure RTCPeerConnection
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
            Debug.Log($"Connection State: {state}");
        };

        peerConnection.OnIceCandidate = candidate =>
        {
            Debug.Log($"ICE Candidate: {candidate}");
        };

        // Create and send offer
        var op = peerConnection.CreateOffer();
        yield return op;

        if (op.IsError)
        {
            Debug.LogError($"Create Offer Error: {op.Error.message}");
            yield break;
        }

        var desc = op.Desc;
        var opLocal = peerConnection.SetLocalDescription(ref desc);
        yield return opLocal;

        if (opLocal.IsError)
        {
            Debug.LogError($"Set Local Description Error: {opLocal.Error.message}");
            yield break;
        }

        // Send offer to signaling server
        var offerJson = new JObject
        {
            ["type"] = desc.type.ToString().ToLower(),
            ["sdp"] = desc.sdp
        };

        var request = new UnityWebRequest(ServerUrl + "/offer", "POST");
        byte[] bodyRaw = Encoding.UTF8.GetBytes(offerJson.ToString());
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");

        yield return request.SendWebRequest();

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"Server Error: {request.error}");
            yield break;
        }

        // Parse and set remote description
        var response = JObject.Parse(request.downloadHandler.text);
        var sdp = response["sdp"].ToString();
        var type = RTCSdpType.Answer;
        var remoteDesc = new RTCSessionDescription
        {
            type = type,
            sdp = sdp
        };

        var opRemote = peerConnection.SetRemoteDescription(ref remoteDesc);
        yield return opRemote;

        if (opRemote.IsError)
        {
            Debug.LogError($"Set Remote Description Error: {opRemote.Error.message}");
            yield break;
        }

        Debug.Log("WebRTC connection established successfully");
    }

    private void UpdateDisplayImage(Texture texture)
    {
        displayImage.texture = texture;
    }

    private RTCConfiguration GetDefaultConfiguration()
    {
        RTCConfiguration config = default;
        config.iceServers = new[]
        {
            new RTCIceServer { urls = new[] { "stun:stun.l.google.com:19302" } }
        };
        return config;
    }

    private void OnDestroy()
    {
        if (videoStreamTrack != null)
        {
            videoStreamTrack.OnVideoReceived -= UpdateDisplayImage;
        }

        if (peerConnection != null)
        {
            peerConnection.Close();
            peerConnection.Dispose();
        }

        if (receiveStream != null)
        {
            receiveStream.Dispose();
        }

        WebRTC.Dispose();
    }
}
