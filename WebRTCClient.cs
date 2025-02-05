using UnityEngine;
using UnityEngine.UI;
using Unity.WebRTC;
using System;
using UnityEngine.Networking;
using System.Text;
using System.Collections;
using System.Linq;

public class WebRTCClient : MonoBehaviour
{
    [SerializeField] private RawImage displayImage;
    [SerializeField] private string serverUrl = "https://34.133.108.164:8443";
    
    private RTCPeerConnection peerConnection;
    private MediaStream videoStream;
    private RenderTexture currentRenderTexture;
    
    // 証明書検証をスキップするための設定
    class AcceptAllCertificatesSignedWithAnyPublicKey : CertificateHandler
    {
        protected override bool ValidateCertificate(byte[] certificateData)
        {
            return true;
        }
    }
    
    void Start()
    {
        // SSL/TLS証明書の検証をスキップ
        Debug.Log("Starting WebRTC connection...");
        StartConnection();
    }

    void OnDestroy()
    {
        StopConnection();
    }

    private void StartConnection()
    {
        var configuration = new RTCConfiguration
        {
            iceServers = new[] { 
                new RTCIceServer { urls = new[] { "stun:stun.l.google.com:19302" } }
            }
        };

        peerConnection = new RTCPeerConnection(ref configuration);
        
        // ICE candidate イベントハンドラの設定
        peerConnection.OnIceCandidate = candidate =>
        {
            if (candidate == null) return;
            Debug.Log($"OnIceCandidate: {candidate.Candidate}");
            // ICE candidateの送信処理を必要に応じて実装
        };
        
        peerConnection.OnIceConnectionChange = state =>
        {
            Debug.Log($"ICE Connection State: {state}");
        };

        peerConnection.OnConnectionStateChange = state =>
        {
            Debug.Log($"Connection State: {state}");
        };

        // Set up event handlers
        peerConnection.OnTrack = (RTCTrackEvent e) =>
        {
            if (e.Track is MediaStreamTrack track && track.Kind == TrackKind.Video)
            {
                videoStream = e.Streams.First(); // VideoStreamを取得
                var videoTrack = track as VideoStreamTrack;
                // VideoStreamTrackのイベントハンドラを設定
                videoTrack.OnVideoReceived += (Texture texture) =>
                {
                    if (texture is Texture2D tex2D)
                    {
                        // デバッグのためにテクスチャに含まれるピクセルの平均と分散を計算
                        var pixels = ((Texture2D)texture).GetPixels();
                        var avg = pixels.Average(p => p.grayscale);
                        var variance = pixels.Average(p => (p.grayscale - avg) * (p.grayscale - avg));
                        Debug.Log($"Average: {avg}, Variance: {variance}");

                        // 前のRenderTextureを解放
                        if (currentRenderTexture != null)
                        {
                            currentRenderTexture.Release();
                        }

                        // RenderTextureをRGBA32フォーマットで作成
                        currentRenderTexture = new RenderTexture(tex2D.width, tex2D.height, 0, RenderTextureFormat.RGBA32);
                        currentRenderTexture.Create();

                        // テクスチャを変換してRenderTextureに描画
                        Graphics.Blit(tex2D, currentRenderTexture);
                        
                        // currentRenderTextureの平均と分散を計算
                        var rtPixels = new Color[currentRenderTexture.width * currentRenderTexture.height];
                        RenderTexture.active = currentRenderTexture;
                        rtPixels = currentRenderTexture.GetPixels();
                        var rtAvg = rtPixels.Average(p => p.grayscale);
                        var rtVariance = rtPixels.Average(p => (p.grayscale - rtAvg) * (p.grayscale - rtAvg));
                        Debug.Log($"RT Average: {rtAvg}, RT Variance: {rtVariance}");

                        displayImage.texture = currentRenderTexture;
                    }
                    else
                    {
                        Debug.LogWarning("Texture is not Texture2D");
                        displayImage.texture = texture;
                    }
                    displayImage.color = Color.white; // 不透明度を最大に設定
                };
            }
        };
        // Start negotiation
        StartCoroutine(Negotiate());
    }

    private IEnumerator Negotiate()
    {
        // Add transceivers (similar to client.js)
        var videoInit = new RTCRtpTransceiverInit { direction = RTCRtpTransceiverDirection.RecvOnly };
        var audioInit = new RTCRtpTransceiverInit { direction = RTCRtpTransceiverDirection.RecvOnly };
        peerConnection.AddTransceiver(TrackKind.Video, videoInit);
        peerConnection.AddTransceiver(TrackKind.Audio, audioInit);

        // Create and set local description
        var op = peerConnection.CreateOffer();
        yield return new WaitUntil(() => op.IsDone);
        
        if (op.IsError)
        {
            Debug.LogError($"Create offer failed: {op.Error.message}");
            yield break;
        }

        var desc = op.Desc;
        var setLocalDesc = peerConnection.SetLocalDescription(ref desc);
        yield return new WaitUntil(() => setLocalDesc.IsDone);

        if (setLocalDesc.IsError)
        {
            Debug.LogError($"Set local description failed: {setLocalDesc.Error.message}");
            yield break;
        }

        // Wait for ICE gathering to complete
        yield return new WaitUntil(() => peerConnection.GatheringState == RTCIceGatheringState.Complete);

        // Send offer to signaling server
        var offer = peerConnection.LocalDescription;
        var jsonOffer = JsonUtility.ToJson(new SignalingMessage
        {
            sdp = offer.sdp,
            type = offer.type.ToString().ToLower()
        });

        using (var request = new UnityWebRequest($"{serverUrl}/offer", "POST"))
        {
            // 証明書検証をスキップする設定を追加
            request.certificateHandler = new AcceptAllCertificatesSignedWithAnyPublicKey();
            byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonOffer);
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");

            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"Failed to send offer: {request.error}");
                yield break;
            }

            // Parse answer
            var response = JsonUtility.FromJson<SignalingMessage>(request.downloadHandler.text);
            RTCSessionDescription answer = new RTCSessionDescription
            {
                type = (RTCSdpType)Enum.Parse(typeof(RTCSdpType), response.type, true),
                sdp = response.sdp
            };

            // Set remote description
            var setRemoteDesc = peerConnection.SetRemoteDescription(ref answer);
            yield return new WaitUntil(() => setRemoteDesc.IsDone);

            if (setRemoteDesc.IsError)
            {
                Debug.LogError($"Set remote description failed: {setRemoteDesc.Error.message}");
                yield break;
            }
        }
    }

    private void StopConnection()
    {
        if (peerConnection != null)
        {
            peerConnection.Close();
            peerConnection.Dispose();
            peerConnection = null;
        }

        if (videoStream != null)
        {
            videoStream.Dispose();
            videoStream = null;
        }

        // RenderTextureのクリーンアップ
        if (currentRenderTexture != null)
        {
            currentRenderTexture.Release();
            currentRenderTexture = null;
        }
    }

    [Serializable]
    private class SignalingMessage
    {
        public string sdp;
        public string type;
    }
}
